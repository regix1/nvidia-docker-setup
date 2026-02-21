#!/bin/bash
#
# Vulkan support installer for Docker containers.
#
# Detects the GPU vendor (NVIDIA, Intel, or AMD) and installs the
# appropriate Vulkan loader and ICD driver.
#
#   NVIDIA  → libvulkan1 + EGL-based ICD JSON (for FFmpeg/libplacebo compat)
#   Intel   → libvulkan1 + mesa-vulkan-drivers + intel-media-va-driver-non-free
#   AMD     → libvulkan1 + mesa-vulkan-drivers
#
# Usage:
#   ./mod-vulkan.sh              # install
#   ./mod-vulkan.sh --uninstall  # remove

set -euo pipefail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

handle_error() {
    echo "An error occurred. Exiting..."
    exit 1
}

APT_UPDATED=0
ensure_apt_updated() {
    if [ "$APT_UPDATED" -eq 0 ]; then
        echo "Updating package lists..."
        export DEBIAN_FRONTEND=noninteractive
        apt-get update || true
        APT_UPDATED=1
    fi
}

install_packages() {
    ensure_apt_updated
    export DEBIAN_FRONTEND=noninteractive
    apt-get install -y --no-install-recommends "$@"
}

detect_gpu() {
    # NVIDIA: container toolkit mounts /dev/nvidia* devices
    if ls /dev/nvidia* &>/dev/null; then
        echo "nvidia"
        return
    fi

    # Intel / AMD: exposed via /dev/dri (--device /dev/dri:/dev/dri)
    if ls /dev/dri/renderD* &>/dev/null; then
        # Try to distinguish via sysfs PCI vendor IDs
        for vendor_file in /sys/bus/pci/devices/*/vendor; do
            [ -f "$vendor_file" ] || continue
            vendor_id=$(cat "$vendor_file" 2>/dev/null || true)
            case "$vendor_id" in
                0x8086) echo "intel"; return ;;
                0x1002) echo "amd";   return ;;
            esac
        done

        # Fallback: lspci if available
        if command -v lspci &>/dev/null; then
            local lspci_out
            lspci_out=$(lspci 2>/dev/null | grep -iE 'vga|3d|display' || true)
            if echo "$lspci_out" | grep -qi intel; then
                echo "intel"; return
            elif echo "$lspci_out" | grep -qiE 'amd|radeon'; then
                echo "amd"; return
            fi
        fi

        # /dev/dri present but vendor unknown — Mesa covers both Intel + AMD
        echo "mesa"
        return
    fi

    echo "unknown"
}

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------

if [ "${1:-}" = "--uninstall" ]; then
    echo "Uninstalling Vulkan support..."
    apt-get remove -y libvulkan1 mesa-vulkan-drivers intel-media-va-driver-non-free vulkan-tools 2>/dev/null || true
    rm -f /etc/vulkan/icd.d/nvidia_egl_icd.json
    apt-get autoremove -y
    echo "Vulkan support successfully uninstalled."
    exit 0
fi

# ---------------------------------------------------------------------------
# Detect GPU
# ---------------------------------------------------------------------------

GPU_VENDOR=$(detect_gpu)
echo "Detected GPU vendor: $GPU_VENDOR"

# ---------------------------------------------------------------------------
# Vendor-specific installation
# ---------------------------------------------------------------------------

case "$GPU_VENDOR" in
    nvidia)
        # NVIDIA container toolkit mounts the driver libraries and ICD.
        # We only need libvulkan1 (loader) and our EGL-based ICD workaround.
        NEEDED=()
        dpkg -s libvulkan1 &>/dev/null    || NEEDED+=(libvulkan1)
        dpkg -s vulkan-tools &>/dev/null  || NEEDED+=(vulkan-tools)

        if [ ${#NEEDED[@]} -gt 0 ]; then
            echo "Installing NVIDIA Vulkan packages: ${NEEDED[*]}"
            install_packages "${NEEDED[@]}"
        fi

        EGL_ICD="/etc/vulkan/icd.d/nvidia_egl_icd.json"

        if [ -f "$EGL_ICD" ]; then
            echo "NVIDIA Vulkan EGL ICD already configured."
        else
            # Read api_version from the driver-mounted ICD
            API_VERSION="1.3.275"
            for src in /etc/vulkan/icd.d/nvidia_icd.json \
                       /usr/share/vulkan/icd.d/nvidia_icd.json \
                       /usr/share/vulkan/icd.d/nvidia_icd.x86_64.json; do
                if [ -f "$src" ]; then
                    ver=$(grep -oP '"api_version"\s*:\s*"\K[0-9]+\.[0-9]+\.[0-9]+' "$src" 2>/dev/null || true)
                    if [ -n "$ver" ]; then
                        API_VERSION="$ver"
                        break
                    fi
                fi
            done

            # Write EGL ICD alongside the driver-mounted GLX one
            echo "Configuring NVIDIA Vulkan EGL ICD..."
            mkdir -p /etc/vulkan/icd.d
            cat > "$EGL_ICD" <<EOF
{
  "file_format_version": "1.0.1",
  "ICD": {
    "library_path": "libEGL_nvidia.so.0",
    "api_version": "$API_VERSION"
  }
}
EOF
        fi
        ;;

    intel)
        # Intel iGPU needs:
        #   libvulkan1                       — Vulkan loader
        #   mesa-vulkan-drivers              — Intel ANV Vulkan driver (for libplacebo)
        #   intel-media-va-driver-non-free   — VA-API driver (for hardware decode/encode, QSV)
        NEEDED=()

        dpkg -s libvulkan1 &>/dev/null                    || NEEDED+=(libvulkan1)
        dpkg -s mesa-vulkan-drivers &>/dev/null            || NEEDED+=(mesa-vulkan-drivers)
        dpkg -s intel-media-va-driver-non-free &>/dev/null || NEEDED+=(intel-media-va-driver-non-free)
        dpkg -s vulkan-tools &>/dev/null                   || NEEDED+=(vulkan-tools)

        if [ ${#NEEDED[@]} -eq 0 ]; then
            echo "All Intel GPU packages already installed."
        else
            echo "Installing Intel GPU packages: ${NEEDED[*]}"
            install_packages "${NEEDED[@]}"
        fi

        # Remove stale NVIDIA ICD files (left over if this container was
        # previously used with an NVIDIA GPU — causes harmless but noisy errors)
        for stale_icd in /etc/vulkan/icd.d/nvidia_egl_icd.json \
                         /etc/vulkan/icd.d/nvidia_icd.json; do
            if [ -f "$stale_icd" ]; then
                echo "Removing stale NVIDIA ICD: $stale_icd"
                rm -f "$stale_icd"
            fi
        done

        # Ensure the render node is accessible
        if [ -e /dev/dri/renderD128 ]; then
            echo "Render node /dev/dri/renderD128 is available."
        else
            echo "Warning: /dev/dri/renderD128 not found — ensure --device /dev/dri:/dev/dri is set."
        fi
        ;;

    amd)
        # AMD GPU needs:
        #   libvulkan1          — Vulkan loader
        #   mesa-vulkan-drivers — AMD RADV Vulkan driver
        NEEDED=()

        dpkg -s libvulkan1 &>/dev/null          || NEEDED+=(libvulkan1)
        dpkg -s mesa-vulkan-drivers &>/dev/null  || NEEDED+=(mesa-vulkan-drivers)
        dpkg -s vulkan-tools &>/dev/null         || NEEDED+=(vulkan-tools)

        if [ ${#NEEDED[@]} -eq 0 ]; then
            echo "All AMD GPU packages already installed."
        else
            echo "Installing AMD GPU packages: ${NEEDED[*]}"
            install_packages "${NEEDED[@]}"
        fi
        ;;

    mesa)
        # /dev/dri present but vendor unknown — install Mesa for both Intel + AMD
        NEEDED=()

        dpkg -s libvulkan1 &>/dev/null          || NEEDED+=(libvulkan1)
        dpkg -s mesa-vulkan-drivers &>/dev/null  || NEEDED+=(mesa-vulkan-drivers)
        dpkg -s vulkan-tools &>/dev/null         || NEEDED+=(vulkan-tools)

        if [ ${#NEEDED[@]} -eq 0 ]; then
            echo "Mesa Vulkan drivers already installed."
        else
            echo "Installing Mesa Vulkan drivers: ${NEEDED[*]}"
            install_packages "${NEEDED[@]}"
        fi
        ;;

    *)
        echo "Warning: Could not detect GPU vendor."
        echo "Installing Mesa Vulkan drivers as fallback..."
        install_packages libvulkan1 mesa-vulkan-drivers vulkan-tools || true
        ;;
esac

echo "Installation complete."

# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

if ldconfig -p | grep -q libvulkan.so.1; then
    echo "Vulkan loader: OK"
else
    echo "Warning: libvulkan.so.1 not found in linker cache."
    ldconfig
    if ldconfig -p | grep -q libvulkan.so.1; then
        echo "Vulkan loader: OK (after ldconfig refresh)"
    else
        echo "Error: Vulkan loader not available."
        exit 1
    fi
fi

# Quick device check for Intel/AMD
if [ "$GPU_VENDOR" != "nvidia" ] && [ -e /dev/dri/renderD128 ]; then
    echo "Render device: OK (/dev/dri/renderD128)"
fi

# Run vulkaninfo if available
if command -v vulkaninfo &>/dev/null; then
    echo "--- vulkaninfo --summary ---"
    vulkaninfo --summary 2>&1 || true
    echo "----------------------------"
fi

echo "Vulkan support successfully installed for: $GPU_VENDOR"
exit 0

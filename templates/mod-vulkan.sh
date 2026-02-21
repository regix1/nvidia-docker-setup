#!/bin/bash
#
# Vulkan support installer for Docker containers.
#
# Detects the GPU vendor (NVIDIA, Intel, or AMD) and installs the
# appropriate Vulkan loader and ICD driver.
#
#   NVIDIA  → libvulkan1 + EGL-based ICD JSON (for FFmpeg/libplacebo compat)
#   Intel   → libvulkan1 + mesa-vulkan-drivers (ANV driver, auto-registers ICD)
#   AMD     → libvulkan1 + mesa-vulkan-drivers (RADV driver, auto-registers ICD)
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
    apt-get remove -y libvulkan1 mesa-vulkan-drivers 2>/dev/null || true
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
# Install Vulkan loader (required for all vendors)
# ---------------------------------------------------------------------------

if dpkg -s libvulkan1 &>/dev/null; then
    echo "libvulkan1 already installed."
else
    echo "Installing Vulkan loader..."
    export DEBIAN_FRONTEND=noninteractive
    if ! apt-get update || ! apt-get install -y --no-install-recommends libvulkan1; then
        handle_error
    fi
fi

# ---------------------------------------------------------------------------
# Vendor-specific configuration
# ---------------------------------------------------------------------------

case "$GPU_VENDOR" in
    nvidia)
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

    intel|amd|mesa)
        # Mesa Vulkan drivers include both Intel ANV and AMD RADV.
        # The package auto-registers its ICD JSON under /usr/share/vulkan/icd.d/.
        if dpkg -s mesa-vulkan-drivers &>/dev/null; then
            echo "Mesa Vulkan drivers already installed."
        else
            echo "Installing Mesa Vulkan drivers..."
            export DEBIAN_FRONTEND=noninteractive
            if ! apt-get install -y --no-install-recommends mesa-vulkan-drivers; then
                handle_error
            fi
        fi
        ;;

    *)
        echo "Warning: Could not detect GPU vendor."
        echo "Installing Mesa Vulkan drivers as fallback..."
        export DEBIAN_FRONTEND=noninteractive
        apt-get install -y --no-install-recommends mesa-vulkan-drivers 2>/dev/null || true
        ;;
esac

echo "Installation complete."

# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

if ldconfig -p | grep -q libvulkan.so.1; then
    echo "Vulkan support successfully installed."
    exit 0
fi

echo "Warning: libvulkan.so.1 not found in linker cache."
exit 1

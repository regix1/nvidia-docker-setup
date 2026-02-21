#!/bin/bash

set -e

EGL_ICD="/etc/vulkan/icd.d/nvidia_egl_icd.json"

handle_error() {
    echo "Error: Installation failed"
    exit 1
}

trap 'handle_error' ERR

if [ "$1" == "--uninstall" ]; then
    echo "Uninstalling Vulkan support..."
    apt-get remove -y libvulkan1 2>/dev/null || true
    apt-get autoremove -y
    rm -f "$EGL_ICD"
    echo "Vulkan support successfully uninstalled."
    exit 0
fi

# Install the Vulkan loader if missing
if dpkg -s libvulkan1 &>/dev/null; then
    echo "libvulkan1 already installed."
else
    echo "Installing Vulkan loader..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends libvulkan1
fi

# Already configured
if [ -f "$EGL_ICD" ]; then
    echo "Vulkan support is already installed."
    exit 0
fi

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

# Verify
if ldconfig -p | grep -q libvulkan.so.1; then
    echo ""
    echo "==================== Installation Complete ===================="
    echo "Vulkan support successfully installed"
    echo "  - libvulkan1 (Vulkan loader)"
    echo "  - NVIDIA EGL ICD (api_version $API_VERSION)"
    echo ""
    exit 0
else
    echo "Error: Failed to verify Vulkan loader installation"
    exit 1
fi

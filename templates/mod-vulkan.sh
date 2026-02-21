#!/bin/bash

EGL_ICD="/etc/vulkan/icd.d/nvidia_egl_icd.json"

# Function to handle errors
function handle_error {
    echo "An error occurred. Exiting..."
    exit 1
}

# Check if the --uninstall option is provided
if [ "$1" == "--uninstall" ]; then
    echo "Uninstalling Vulkan support..."
    if apt-get remove -y libvulkan1 && rm -f "$EGL_ICD"; then
        apt-get autoremove -y
        echo "Vulkan support successfully uninstalled."
        exit 0
    else
        handle_error
    fi
fi

# Check if already fully configured
if dpkg -s libvulkan1 &>/dev/null && [ -f "$EGL_ICD" ]; then
    echo "Vulkan support is already installed."
    exit 0
fi

# Install the Vulkan loader if missing
if dpkg -s libvulkan1 &>/dev/null; then
    echo "libvulkan1 already installed."
else
    echo "Installing Vulkan loader..."
    export DEBIAN_FRONTEND=noninteractive
    if ! apt-get update || ! apt-get install -y --no-install-recommends libvulkan1; then
        handle_error
    fi
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

echo "Installation complete."

# Verify installation
if ldconfig -p | grep -q libvulkan.so.1 && [ -f "$EGL_ICD" ]; then
    echo "Vulkan support successfully installed."
    exit 0
fi

echo "Failed to install Vulkan support."
exit 1

# NVIDIA Docker Setup - Python Version

A modular Python tool for installing and configuring NVIDIA drivers with Docker support, optimized for media processing and Plex servers.

## Features

- **Smart Detection**: Automatically detects existing installations
- **Interactive Menus**: Clear, user-friendly interface
- **Selective Installation**: Install only what you need
- **NVIDIA Driver Management**: Automated driver installation with version selection
- **Docker Integration**: Complete Docker setup with NVIDIA Container Toolkit
- **CUDA Version Control**: Easy CUDA version selection for containers
- **Vulkan Support**: Full Vulkan setup for GPU compute (NCNN, video upscaling)
- **NVENC Patches**: Optional patches for unlimited encoding sessions
- **Media Server Templates**: Pre-configured Plex and FFmpeg setups
- **Comprehensive Validation**: System checks and GPU capability testing

## Quick Start

```bash
# Clone the repository
git clone <your-repo-url>
cd nvidia-docker-setup

# Run the installer (as regular user)
chmod +x install.sh
./install.sh

# Run the main setup (as root)
sudo python3 main.py
```

## New Improved Interface

The script now features a much cleaner interface:

### 1. **System Detection**
```
System Status:
  NVIDIA Driver: ✓ 550.67 
  Docker:        ✓ 24.0.6
  NVIDIA Runtime: ✓ Available
```

### 2. **Smart Menu System**
```
Select installation options:
  1. Reinstall NVIDIA Drivers (Current: 580.95) [OK]
     Reinstall or update NVIDIA drivers

  2. Reconfigure Docker (Current: 28.0.1) [OK]
     Reconfigure Docker with NVIDIA support

  3. Select CUDA Version
     Choose CUDA version for containers

  4. Setup Vulkan Support [OK]
     Install Vulkan for GPU compute (NCNN, etc.)

  5. Apply NVIDIA Patches (NVENC/NvFBC)
     Remove NVENC session limits and enable NvFBC

  6. Configure for Media Servers
     Optimize Docker for Plex/media processing

  7. Complete Installation (All Components)
     Install/configure everything automatically
```

### 3. **Clear CUDA Selection**
```
Available CUDA versions for containers:
  1. 12.4.0 - Latest stable release - RTX 40 series optimized (recommended)
  2. 12.3.2 - Previous stable - Wide compatibility
  3. 12.2.2 - LTS candidate - Enterprise ready
  4. 12.1.1 - Stable release - Good performance
  5. 11.8.0 - Legacy support - Mature and stable
  6. Enter custom version
```

## Key Improvements

### **Better User Experience**
- Detects what's already installed before asking to install
- Shows current versions of installed components
- Clear menu options with descriptions
- No more confusing duplicate choices

### **Smart Installation Logic**
- Only asks to reinstall if something is already installed
- Skips unnecessary steps automatically
- Validates system state before proceeding
- Provides clear feedback on what's happening

### **Improved Error Handling**
- Better validation of user inputs
- Clearer error messages
- Graceful handling of missing files
- Recovery suggestions for common issues

## Requirements

- Ubuntu 22.04 (Jammy) - other versions may work but are untested
- NVIDIA GPU (required)
- Root/sudo access
- Internet connection

## Project Structure

```
nvidia-docker-setup/
├── main.py                 # Entry point
├── requirements.txt        # Python dependencies
├── src/                   # Source code modules
│   ├── utils/            # Logging, system utilities, prompts
│   ├── nvidia/           # NVIDIA driver, CUDA, Vulkan, patches
│   │   ├── drivers.py    # Driver installation and management
│   │   ├── cuda.py       # CUDA version selection
│   │   ├── vulkan.py     # Vulkan setup and verification
│   │   └── patches.py    # NVENC/NvFBC patches
│   ├── docker/           # Docker setup and configuration
│   └── system/           # System checks and validation
├── templates/            # Configuration templates
│   ├── docker-daemon.json
│   ├── docker-daemon-cgroupfs.json
│   └── plex-nvidia.yml
└── configs/             # Configuration files
    └── cuda_versions.json
```

## Installation Process

The script performs these steps:

1. **System Checks**: Validates OS, GPU presence, and dependencies
2. **Performance Recommendations**: Displays kernel parameter suggestions
3. **NVIDIA Drivers**: Installs or updates NVIDIA drivers
4. **CUDA Selection**: Allows choosing CUDA version
5. **Docker Setup**: Installs Docker with NVIDIA Container Toolkit
6. **Optional Patches**: Applies NVENC/NvFBC patches if requested
7. **Configuration**: Optimizes Docker for media processing
8. **Validation**: Tests GPU capabilities and Docker integration

## Key Features

### NVIDIA Driver Management
- Automatic detection of recommended driver versions
- Manual driver version selection
- Driver cleanup and conflict resolution
- Post-installation validation

### Docker Integration
- Complete Docker CE installation
- NVIDIA Container Toolkit setup
- Runtime configuration for GPU access
- Optional cgroupfs driver for compatibility

### Media Optimization
- Pre-configured Plex docker-compose template
- FFmpeg container examples
- GPU-accelerated encoding/decoding setup
- NVENC session limit removal

### System Validation
- GPU capability detection (NVENC/NVDEC)
- Architecture compatibility checks
- Docker-NVIDIA integration testing
- Performance recommendations

### Vulkan Support
Vulkan is required for GPU compute applications like NCNN (video upscaling, AI inference):
- Automatic installation of Vulkan libraries and tools
- NVIDIA Vulkan ICD configuration
- `libnvidia-gl` package installation for GPU-accelerated Vulkan
- Container Device Interface (CDI) generation for Docker
- Verification and diagnostic tools

## Templates

### Plex Media Server
Located at `templates/plex-nvidia.yml`:
- GPU-accelerated transcoding
- Proper NVIDIA runtime configuration
- Volume mapping examples
- Environment variable setup

### Docker Daemon Configuration
- `docker-daemon.json`: Standard NVIDIA configuration
- `docker-daemon-cgroupfs.json`: Alternative for compatibility issues

## Usage Examples

### Basic Installation
```bash
sudo python3 main.py
```

### Testing GPU Integration
```bash
# Test NVIDIA Docker integration
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi

# Test with Plex (after configuration)
cd /opt/docker-templates
docker-compose -f plex-nvidia.yml up -d
```

### Testing Vulkan Support
```bash
# Test Vulkan on host
vulkaninfo --summary

# Test Vulkan in Docker container
docker run --rm --gpus all \
  -e NVIDIA_DRIVER_CAPABILITIES=all \
  nvidia/cuda:12.0-base \
  bash -c "apt update && apt install -y vulkan-tools && vulkaninfo --summary"
```

### Docker Compose with Vulkan
For containers requiring Vulkan (NCNN, video upscaling, AI inference):

```yaml
services:
  my-vulkan-app:
    image: your-image:latest
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu, compute, video, utility]
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
      - NVIDIA_DRIVER_CAPABILITIES=all
      - VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_icd.json
```

### Manual Module Usage
```python
from src.nvidia.drivers import select_nvidia_driver
from src.docker.setup import setup_docker

# Install just NVIDIA drivers
select_nvidia_driver()

# Setup just Docker
setup_docker()
```

## Troubleshooting

### Common Issues

**"CUDA_ERROR_NO_DEVICE" in containers:**
- Run the script and select cgroupfs driver option
- Reboot after installation

**Driver version mismatch:**
- Use the cleanup option when prompted
- Reboot after driver installation

**Docker permission denied:**
- Add user to docker group: `sudo usermod -aG docker $USER`
- Log out and back in

**NVENC not working:**
- Apply the NVENC patch when prompted
- Verify GPU model supports NVENC

**Vulkan showing "llvmpipe" (software renderer) instead of NVIDIA GPU:**
- Ensure `libnvidia-gl-XXX` is installed (XXX = driver version number)
- Update nvidia-container-toolkit: `sudo apt install nvidia-container-toolkit`
- Regenerate CDI specification: `sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml`
- Restart Docker: `sudo systemctl restart docker`
- Reboot the system if issues persist

**Vulkan not working in Docker containers:**
- Set `NVIDIA_DRIVER_CAPABILITIES=all` in your container environment
- Verify the host has working Vulkan: `vulkaninfo --summary`
- Check Vulkan ICD exists: `ls /usr/share/vulkan/icd.d/nvidia_icd.json`
- Ensure nvidia-container-toolkit version 1.14+ is installed

### Manual Fixes

**Reset Docker NVIDIA configuration:**
```bash
sudo rm /etc/docker/daemon.json
sudo systemctl restart docker
sudo python3 main.py  # Re-run configuration
```

**Check GPU status:**
```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi
```

## Performance Recommendations

For optimal performance, add these kernel parameters to GRUB:
```
pcie_port_pm=off pcie_aspm.policy=performance
```

Edit `/etc/default/grub` and add to `GRUB_CMDLINE_LINUX_DEFAULT`, then run:
```bash
sudo update-grub
sudo reboot
```

## Contributing

The modular structure makes it easy to:
- Add new NVIDIA driver versions
- Update Docker installation procedures  
- Add new media server templates
- Extend system validation checks

## License

This project is provided as-is for educational and personal use.

## Acknowledgments

- NVIDIA for GPU drivers and Container Toolkit
- [keylase/nvidia-patch](https://github.com/keylase/nvidia-patch) for NVENC patches
- Docker for containerization platform
# NVIDIA Docker Setup - Python Version

A modular Python tool for installing and configuring NVIDIA drivers with Docker support, optimized for media processing and Plex servers.

## Features

- ✅ Automated NVIDIA driver installation with version selection
- ✅ Docker installation with NVIDIA Container Toolkit
- ✅ CUDA version management
- ✅ Optional NVENC/NvFBC patches for unlimited sessions
- ✅ Pre-configured templates for Plex and FFmpeg
- ✅ Comprehensive system validation
- ✅ Modular Python architecture for easy maintenance

## Quick Start

```bash
git clone <your-repo>
cd nvidia-docker-setup
sudo python3 main.py
```

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
│   ├── nvidia/           # NVIDIA driver, CUDA, patches
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
docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi

# Test with Plex (after configuration)
cd /opt/docker-templates
docker-compose -f plex-nvidia.yml up -d
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
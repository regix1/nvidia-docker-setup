# NVIDIA Docker Setup

A modular Python tool for installing and configuring NVIDIA drivers with Docker support, optimized for media processing and Plex servers.

## Features

- **Smart Detection**: Automatically detects existing installations
- **Interactive Menus**: Clear, user-friendly interface
- **Selective Installation**: Install only what you need
- **NVIDIA Driver Management**: Automated driver installation with version selection
- **Docker Integration**: Complete Docker setup with NVIDIA Container Toolkit
- **CUDA Version Control**: Easy CUDA version selection for containers
- **NVENC/NvFBC Patches**: Binary-safe patches for unlimited encoding sessions
- **Media Server Templates**: Pre-configured Plex and FFmpeg setups
- **GPU Capability Testing**: System checks and validation

## Quick Start

```bash
git clone https://github.com/regix1/nvidia-docker-setup.git
cd nvidia-docker-setup
sudo bash setup.sh
```

## Interface

### System Detection
```
Installation Status:
  NVIDIA Driver:  [OK] 580.126.09
  Docker:         [OK] 28.0.1
  NVIDIA Runtime: [OK] Available
```

### Menu System
```
Select installation options:
  1. Reinstall NVIDIA Drivers (Current: 580.126.09) [OK]
     Reinstall or update NVIDIA drivers

  2. Reconfigure Docker (Current: 28.0.1) [OK]
     Reconfigure Docker with NVIDIA support

  3. Select CUDA Version
     Choose CUDA version for containers

  4. Apply NVIDIA Patches (NVENC/NvFBC)
     Remove NVENC session limits and enable NvFBC

  5. Configure for Media Servers
     Optimize Docker for Plex/media processing

  6. Complete Installation (All Components)
     Install/configure everything automatically

  7. Exit
     Exit without changes
```

### CUDA Selection
```
Available CUDA versions for containers:
  1. 12.4.0 - Latest stable release - RTX 40 series optimized (recommended)
  2. 12.3.2 - Previous stable - Wide compatibility
  3. 12.2.2 - LTS candidate - Enterprise ready
  4. 12.1.1 - Stable release - Good performance
  5. 11.8.0 - Legacy support - Mature and stable
  6. Enter custom version
```

## Requirements

- Ubuntu 22.04+ (other Debian-based distros may work)
- NVIDIA GPU
- Root/sudo access
- Internet connection
- Python 3

## Project Structure

```
nvidia-docker-setup/
├── setup.sh                # Entry point (the only script you need)
├── main.py                 # Python application
├── requirements.txt        # Python dependencies
├── src/
│   ├── utils/              # Logging, system utilities, prompts
│   ├── nvidia/
│   │   ├── drivers.py      # Driver installation and management
│   │   ├── cuda.py         # CUDA version selection
│   │   └── patches.py      # NVENC/NvFBC patch orchestration
│   ├── docker/             # Docker setup and configuration
│   └── system/             # System checks and validation
├── templates/
│   ├── docker-daemon.json
│   ├── docker-daemon-cgroupfs.json
│   └── plex-nvidia.yml
└── configs/
    └── cuda_versions.json
```

## NVENC Session Limit Patch

Consumer GeForce GPUs have an artificial limit on concurrent NVENC encoding sessions. This tool includes a custom binary patcher that removes the limit by modifying `libnvidia-encode.so`.

**How it works:**
- Uses Python3 to scan the binary for the session-check pattern
- Anchor-based matching ensures only the correct location is patched (unlike sed-based approaches that can corrupt the binary)
- Automatically detects the byte-pattern variant for the installed driver
- Supports all modern NVIDIA driver versions
- Creates a backup before patching with rollback support

The patch is applied automatically through the interactive menu (option 4).

## Usage

### Basic Installation
```bash
sudo bash setup.sh
```

### Testing GPU Integration
```bash
# Test NVIDIA Docker integration
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi

# Test with Plex (after configuration)
cd /opt/docker-templates
docker-compose -f plex-nvidia.yml up -d
```

## Templates

### Plex Media Server
Located at `templates/plex-nvidia.yml`:
- GPU-accelerated transcoding
- NVIDIA runtime configuration
- Volume mapping examples

### Docker Daemon Configuration
- `docker-daemon.json`: Standard NVIDIA configuration
- `docker-daemon-cgroupfs.json`: Alternative for compatibility issues

## Troubleshooting

**"CUDA_ERROR_NO_DEVICE" in containers:**
- Run the script and select cgroupfs driver option
- Reboot after installation

**Driver version mismatch:**
- Use the cleanup option when prompted
- Reboot after driver installation

**Docker permission denied:**
- Add user to docker group: `sudo usermod -aG docker $USER`
- Log out and back in

**NVENC "incompatible client key" after patching:**
- This usually means the wrong bytes were patched (common with sed-based tools)
- Re-run the setup and use the NVENC patch option, which uses anchor-based matching

**NVENC not working:**
- Apply the NVENC patch from the menu (option 4)
- Verify GPU model supports NVENC

**Reset Docker NVIDIA configuration:**
```bash
sudo rm /etc/docker/daemon.json
sudo systemctl restart docker
sudo bash setup.sh  # Re-run configuration
```

**Check GPU status:**
```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
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

## License

This project is provided as-is for educational and personal use.

## Acknowledgments

- NVIDIA for GPU drivers and Container Toolkit
- [keylase/nvidia-patch](https://github.com/keylase/nvidia-patch) for upstream NVENC patches
- Docker for containerization platform

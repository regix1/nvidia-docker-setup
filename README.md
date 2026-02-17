# NVIDIA Driver Setup

A CLI tool for installing and configuring NVIDIA drivers with Docker support on Ubuntu/Debian, built for media server hardware acceleration.

## Features

- **Multi-select menu** - pick multiple tasks and run them in one go
- **NVIDIA driver management** - automated install with version selection and cleanup
- **Docker + NVIDIA runtime** - Docker CE and NVIDIA Container Toolkit setup
- **Live CUDA version discovery** - fetches available versions from Docker Hub in real-time
- **NVENC/NvFBC binary patcher** - removes encoding session limits using anchor-based pattern matching
- **Media server config** - pre-configured Docker Compose for Plex with GPU transcoding
- **Self-update** - pulls latest changes from GitHub and reinstalls
- **Smart detection** - detects existing drivers, Docker, and NVIDIA runtime before prompting

## Install

```bash
git clone https://github.com/regix1/nvidia-driver-setup.git
cd nvidia-driver-setup
sudo bash setup.sh
```

`setup.sh` auto-installs the package on first run and launches the tool. On subsequent runs it launches directly.

### Alternative: pip from GitHub

```bash
pip install git+https://github.com/regix1/nvidia-driver-setup.git
sudo nvidia-setup
```

## Usage

Run `sudo nvidia-setup` and use the multi-select menu to toggle items:

```
Installation Status:
  NVIDIA Driver:  [OK] 580.126.09
  Docker:         [OK] 28.0.1
  NVIDIA Runtime: [OK] Available

Select items to run (toggle numbers, Enter to execute):
  0. Exit
  [*] 1. Reinstall NVIDIA Drivers (Current: 580.126.09) [OK]
          Reinstall or update NVIDIA drivers
  [ ] 2. Reconfigure Docker (Current: 28.0.1) [OK]
          Reconfigure Docker with NVIDIA support
  [ ] 3. Select CUDA Version
          Choose CUDA version for containers
  [*] 4. Apply NVIDIA Patches (NVENC/NvFBC)
          Remove NVENC session limits and enable NvFBC
  [ ] 5. Configure for Media Servers
          Optimize Docker for Plex/media processing
  [ ] 6. Update nvidia-setup
          Check for and apply updates to this tool

2 item(s) selected.  Enter numbers to toggle | 'a' = toggle all | Enter = run selected | 0 = exit
```

Selected items execute in dependency order: drivers first, then Docker, CUDA, patches, media config, and self-update last.

## CUDA Version Discovery

CUDA versions are fetched live from the Docker Hub `nvidia/cuda` image tags. The tool shows minimum driver requirements from NVIDIA's release notes alongside each version:

```
Available CUDA versions for containers:
  1. 13.1.1 - Latest - RTX 50 series / Blackwell  (min driver: 590.48.01) (recommended)
  2. 13.1.0 - Latest - RTX 50 series / Blackwell  (min driver: 590.44.01)
  3. 13.0.2 - Latest - RTX 50 series / Blackwell  (min driver: 580.95.05)
  ...
  27. 11.8.0 - Legacy - Proven stability  (min driver: 520.61.05)
  28. 11.7.1 - Legacy - Proven stability  (min driver: 515.48.07)
  29. Enter custom version
```

Falls back to an offline list if Docker Hub is unreachable.

## NVENC Session Limit Patch

Consumer GeForce GPUs limit concurrent NVENC encoding sessions. This tool removes that limit by patching `libnvidia-encode.so` directly.

Unlike sed-based approaches (which can corrupt the binary by matching multiple locations), this patcher uses anchor-based pattern matching to locate the exact session-check instruction sequence, then patches only that location. Supports all modern driver versions with automatic pattern detection.

## Self-Update

The tool can update itself (menu option 6). It pulls the latest changes from `https://github.com/regix1/nvidia-driver-setup.git` and reinstalls the package.

Self-update always runs last in the execution order. The current session continues with the old code; changes take effect on next launch.

## Project Structure

```
nvidia-driver-setup/
├── setup.sh                         # Smart launcher
├── main.py                          # Backwards-compat wrapper
├── pyproject.toml                   # pip package config
├── nvidia_driver_setup/
│   ├── cli.py                       # Multi-select menu and execution
│   ├── updater.py                   # Self-update (git/pip)
│   ├── nvidia/
│   │   ├── drivers.py               # Driver install + cleanup
│   │   ├── cuda.py                  # CUDA version selection (Docker Hub API)
│   │   └── patches.py               # NVENC/NvFBC binary patcher
│   ├── docker/
│   │   ├── setup.py                 # Docker + NVIDIA runtime install
│   │   └── config.py                # Media server Docker config
│   ├── system/
│   │   └── checks.py                # System checks, GPU detection
│   └── utils/
│       ├── logging.py               # Color log helpers
│       ├── prompts.py               # yes/no, choice, multi-select prompts
│       └── system.py                # run_command(), AptManager
├── templates/
│   ├── docker-daemon.json
│   ├── docker-daemon-cgroupfs.json
│   └── plex-nvidia.yml
└── configs/
    └── cuda_versions.json           # Offline CUDA version fallback
```

## Requirements

- Ubuntu 22.04+ (Debian-based)
- NVIDIA GPU
- Root access (`sudo`)
- Python 3.10+
- Internet connection (for driver/Docker downloads; CUDA list has offline fallback)

## Troubleshooting

**CUDA_ERROR_NO_DEVICE in containers** - select the cgroupfs driver option when prompted, then reboot.

**Driver version mismatch** - use the cleanup option when prompted, then reboot.

**Docker permission denied** - `sudo usermod -aG docker $USER`, then log out and back in.

**NVENC "incompatible client key"** - re-run and use menu option 4 (anchor-based patcher). This usually means a sed-based tool previously patched the wrong location.

**Test GPU integration:**

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi
```

## Performance

For optimal GPU performance, add kernel parameters to GRUB:

```bash
# Edit /etc/default/grub, add to GRUB_CMDLINE_LINUX_DEFAULT:
pcie_port_pm=off pcie_aspm.policy=performance

sudo update-grub && sudo reboot
```

## License

Provided as-is for educational and personal use.

## Acknowledgments

- [keylase/nvidia-patch](https://github.com/keylase/nvidia-patch) for upstream NVENC patch research
- NVIDIA for GPU drivers and Container Toolkit

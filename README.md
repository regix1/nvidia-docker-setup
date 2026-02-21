# GPU Driver Setup

A CLI tool for installing and configuring GPU drivers, Vulkan, and Docker on Ubuntu/Debian systems. Built for media server hardware acceleration across NVIDIA, Intel, and AMD GPUs.

## Overview

The tool presents a multi-select menu where you pick one or more tasks and execute them together. It detects your installed GPUs via `lspci`, identifies the vendor (NVIDIA, Intel, or AMD), and tracks per-GPU capabilities including Vulkan, NVENC, NVDEC, CUDA, and Quick Sync Video. Existing drivers, Docker, and runtime state are detected automatically before prompting, so the menu always reflects what is already configured.

Driver management covers automated NVIDIA driver installation with version selection and cleanup. Docker CE and the NVIDIA Container Toolkit are configured together. CUDA container versions are discovered live from Docker Hub with minimum driver requirements shown inline. The NVENC/NvFBC binary patcher removes encoding session limits on consumer GeForce GPUs. A media server configuration option generates Docker Compose setups for Plex with GPU transcoding. The tool can also update itself from GitHub.

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

## Multi-GPU Vendor Detection

The tool scans for all GPUs present in the system using `lspci` and identifies each by vendor and model. NVIDIA, Intel, and AMD GPUs are all recognized. Per-GPU capabilities are tracked so the tool knows which acceleration features are available: Vulkan, NVENC/NVDEC, CUDA, and Intel Quick Sync. This information feeds into driver installation decisions, Vulkan configuration, and encoder selection throughout the tool and its templates.

## Vulkan Support

Vulkan installation and configuration is handled both on the host and inside Docker containers. The host-side installer fetches the LunarG Vulkan SDK tarball directly (APT-based installation was deprecated by LunarG in May 2025) and configures validation layers, SPIR-V tools, headers, and `vulkaninfo`.

For Docker containers, the `mod-vulkan.sh` template detects the GPU vendor and installs the correct Vulkan loader and ICD driver. NVIDIA containers get the EGL-based ICD JSON required for FFmpeg and libplacebo compatibility. Intel containers receive the ANV Vulkan driver and Intel Media VA driver. AMD containers get the RADV mesa driver. The script supports both install and uninstall modes.

## FileFlows Integration

The `dovi5-to-sdr.js` template is a FileFlows processing script for converting Dolby Vision Profile 5 video to SDR. Profile 5 uses DV's proprietary IPTPQc2 color space in the base layer, which standard HDR-to-SDR tone-mapping filters cannot read (producing purple/green output). This script uses libplacebo through Vulkan, the only FFmpeg filter that natively understands IPTPQc2 and applies the DV RPU reshaping metadata for correct colors.

The pipeline is: Decode, Vulkan upload, libplacebo tone-map (BT.2390 curve), download, then hardware or software encode. Encoder selection is automatic with priority order: NVENC on NVIDIA GPUs, Quick Sync on Intel GPUs, then libx265 software fallback. Audio and subtitle streams are copied without re-encoding. Connect the script to Output 3 of the "Detect DV Profile" flow node in FileFlows.

## CUDA Version Discovery

CUDA versions are fetched live from the Docker Hub `nvidia/cuda` image tags. The tool shows minimum driver requirements alongside each version:

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

Unlike sed-based approaches that can corrupt the binary by matching multiple locations, this patcher uses anchor-based pattern matching to locate the exact session-check instruction sequence, then patches only that location. Supports all modern driver versions with automatic pattern detection.

## Self-Update

The tool can update itself via menu option 6. It pulls the latest changes from the GitHub repository and reinstalls the package.

Self-update always runs last in the execution order. The current session continues with the old code and changes take effect on next launch.

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
│   │   ├── cuda_toolkit.py          # CUDA toolkit management
│   │   ├── patches.py               # NVENC/NvFBC binary patcher
│   │   └── vulkan.py                # Vulkan SDK install (LunarG)
│   ├── docker/
│   │   ├── setup.py                 # Docker + NVIDIA runtime install
│   │   └── config.py                # Media server Docker config
│   ├── system/
│   │   └── checks.py                # GPU detection, vendor ID, capabilities
│   └── utils/
│       ├── logging.py               # Color log helpers
│       ├── prompts.py               # yes/no, choice, multi-select prompts
│       └── system.py                # run_command(), AptManager
├── templates/
│   ├── docker-daemon.json           # Docker daemon config
│   ├── docker-daemon-cgroupfs.json  # Docker daemon config (cgroupfs)
│   ├── dovi5-to-sdr.js              # FileFlows DV5-to-SDR script
│   ├── mod-vulkan.sh                # Multi-vendor Vulkan installer for Docker
│   └── plex-nvidia.yml              # Plex Docker Compose template
└── configs/
    ├── cuda_versions.json           # Offline CUDA version fallback
    └── vulkan_versions.json         # Vulkan version data
```

## Requirements

The tool requires Ubuntu 22.04 or later (Debian-based). At least one supported GPU (NVIDIA, Intel, or AMD) should be present. Root access via `sudo` is needed for driver and Docker operations. Python 3.10 or newer must be installed. An internet connection is required for driver and Docker downloads, though the CUDA version list has an offline fallback.

## Troubleshooting

**CUDA_ERROR_NO_DEVICE in containers** -- select the cgroupfs driver option when prompted, then reboot.

**Driver version mismatch** -- use the cleanup option when prompted, then reboot.

**Docker permission denied** -- run `sudo usermod -aG docker $USER`, then log out and back in.

**NVENC "incompatible client key"** -- re-run and use menu option 4 (anchor-based patcher). This usually means a sed-based tool previously patched the wrong location.

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

The NVENC patch research is based on work from [keylase/nvidia-patch](https://github.com/keylase/nvidia-patch). Vulkan SDK distribution is provided by [LunarG](https://vulkan.lunarg.com/).

"""System checks and validation"""

import subprocess
import sys
import os
import re
from ..utils.logging import log_info, log_warn, log_error, log_step
from ..utils.prompts import prompt_yes_no
from ..utils.system import run_command, AptManager, cleanup_nvidia_repos, cleanup_old_nvidia_drivers, full_nvidia_cleanup, check_internet, get_os_info, check_nvidia_gpu, detect_gpu_vendors

_ACKNOWLEDGED_MARKER = "/var/lib/nvidia-setup/.acknowledged"


def get_system_info():
    """Gather comprehensive system information"""
    info = {
        'os': {},
        'kernel': None,
        'gpu': {},
        'gpu_vendors': [],
        'gpus': [],
        'capabilities': {
            'vulkan_supported': False,
            'nvenc_supported': False,
            'nvdec_supported': False,
            'cuda_supported': False,
            'qsv_supported': False,
        }
    }

    # OS Information
    os_info = get_os_info()
    info['os'] = {
        'name': os_info.get('NAME', 'Unknown'),
        'version': os_info.get('VERSION_ID', 'Unknown'),
        'pretty_name': os_info.get('PRETTY_NAME', 'Unknown OS'),
        'codename': os_info.get('UBUNTU_CODENAME') or os_info.get('VERSION_CODENAME', 'unknown')
    }

    # Kernel version
    try:
        info['kernel'] = run_command("uname -r", capture_output=True, check=False)
    except Exception:
        info['kernel'] = "Unknown"

    # Detect GPU vendors
    info['gpu_vendors'] = detect_gpu_vendors()

    # GPU Information from lspci (all vendors)
    try:
        lspci_output = run_command("lspci | grep -iE 'vga|3d|display'", capture_output=True, check=False)
        if lspci_output:
            for line in lspci_output.strip().split('\n'):
                gpu_entry: dict[str, str] = {}
                line_lower = line.lower()

                if 'nvidia' in line_lower:
                    match = re.search(r'NVIDIA Corporation (.+?)(?:\s*\(rev|$)', line, re.IGNORECASE)
                    gpu_entry['vendor'] = 'nvidia'
                    gpu_entry['model'] = match.group(1).strip() if match else line.strip()
                elif 'intel' in line_lower:
                    match = re.search(r'Intel Corporation (.+?)(?:\s*\(rev|$)', line, re.IGNORECASE)
                    gpu_entry['vendor'] = 'intel'
                    gpu_entry['model'] = match.group(1).strip() if match else line.strip()
                elif 'amd' in line_lower or 'radeon' in line_lower:
                    match = re.search(r'(?:AMD|ATI)[^:]*?(?:Corporation\s+)?(.+?)(?:\s*\(rev|$)', line, re.IGNORECASE)
                    gpu_entry['vendor'] = 'amd'
                    gpu_entry['model'] = match.group(1).strip() if match else line.strip()
                else:
                    gpu_entry['vendor'] = 'unknown'
                    gpu_entry['model'] = line.strip()

                if gpu_entry:
                    info['gpus'].append(gpu_entry)

            # Set primary GPU model for backward compatibility
            if info['gpus']:
                info['gpu']['model'] = info['gpus'][0]['model']

    except Exception as e:
        info['gpu']['error'] = str(e)

    # NVIDIA-specific details from nvidia-smi
    if 'nvidia' in info['gpu_vendors']:
        try:
            nvidia_smi_output = run_command(
                "nvidia-smi --query-gpu=gpu_name,driver_version,compute_cap --format=csv,noheader",
                capture_output=True, check=False,
            )
            _error_indicators = ["command not found", "failed", "mismatch", "nvml"]
            if (nvidia_smi_output
                    and not any(err in nvidia_smi_output.lower() for err in _error_indicators)
                    and ',' in nvidia_smi_output):
                parts = nvidia_smi_output.split(',')
                if len(parts) >= 1:
                    info['gpu']['name'] = parts[0].strip()
                if len(parts) >= 2:
                    info['gpu']['driver_version'] = parts[1].strip()
                if len(parts) >= 3:
                    info['gpu']['compute_capability'] = parts[2].strip()

                _determine_gpu_capabilities(info)
            elif nvidia_smi_output and "mismatch" in nvidia_smi_output.lower():
                info['gpu']['driver_note'] = "Driver/library mismatch - reboot required"
        except Exception:
            pass

    # Intel-specific capabilities
    if 'intel' in info['gpu_vendors']:
        info['capabilities']['vulkan_supported'] = True
        info['capabilities']['qsv_supported'] = True

    # AMD-specific capabilities
    if 'amd' in info['gpu_vendors']:
        info['capabilities']['vulkan_supported'] = True

    return info


def _determine_gpu_capabilities(info):
    """Determine GPU capabilities based on compute capability and architecture"""
    compute_cap = info['gpu'].get('compute_capability', '')
    gpu_name = info['gpu'].get('name', '').lower()

    # Parse compute capability (e.g., "8.6" -> 8.6)
    try:
        if compute_cap:
            major, minor = compute_cap.split('.')
            cc_value = float(f"{major}.{minor}")
        else:
            cc_value = 0
    except:
        cc_value = 0

    # Vulkan support: Kepler (3.0) and newer
    # Actually Vulkan requires Maxwell Gen 2 (5.0) or newer for full support
    info['capabilities']['vulkan_supported'] = cc_value >= 5.0

    # CUDA support: All NVIDIA GPUs with drivers
    info['capabilities']['cuda_supported'] = cc_value > 0

    # NVENC support varies by GPU
    # - Kepler (6xx, 7xx) - limited NVENC
    # - Maxwell and newer - good NVENC
    # - Turing and newer - excellent NVENC with more codecs
    info['capabilities']['nvenc_supported'] = cc_value >= 3.0

    # NVDEC support
    info['capabilities']['nvdec_supported'] = cc_value >= 3.0

    # Architecture name
    if cc_value >= 10.0:
        info['gpu']['architecture'] = "Blackwell (RTX 50 series)"
    elif cc_value >= 8.9:
        info['gpu']['architecture'] = "Ada Lovelace (RTX 40 series)"
    elif cc_value >= 8.0:
        info['gpu']['architecture'] = "Ampere (RTX 30 series)"
    elif cc_value >= 7.5:
        info['gpu']['architecture'] = "Turing (RTX 20/GTX 16 series)"
    elif cc_value >= 7.0:
        info['gpu']['architecture'] = "Volta"
    elif cc_value >= 6.0:
        info['gpu']['architecture'] = "Pascal (GTX 10 series)"
    elif cc_value >= 5.0:
        info['gpu']['architecture'] = "Maxwell (GTX 9xx series)"
    elif cc_value >= 3.0:
        info['gpu']['architecture'] = "Kepler (GTX 6xx/7xx series)"
        info['capabilities']['vulkan_supported'] = False  # Limited Vulkan on Kepler
    else:
        info['gpu']['architecture'] = "Unknown/Legacy"


def display_system_info(info):
    """Display system information in a formatted way"""
    print("\n" + "=" * 60)
    print("                    SYSTEM INFORMATION")
    print("=" * 60)

    # OS Info
    print(f"\n  Operating System: {info['os']['pretty_name']}")
    print(f"  Kernel:           {info['kernel']}")

    # GPU Info — show all detected GPUs
    gpus = info.get('gpus', [])
    if gpus:
        for i, gpu in enumerate(gpus):
            label = "GPU" if len(gpus) == 1 else f"GPU {i + 1}"
            vendor_tag = gpu['vendor'].upper()
            print(f"\n  {label}:            [{vendor_tag}] {gpu['model']}")
    elif info['gpu'].get('model'):
        print(f"\n  GPU Model:        {info['gpu']['model']}")

    # NVIDIA-specific details (from nvidia-smi)
    if info['gpu'].get('architecture'):
        print(f"  Architecture:     {info['gpu']['architecture']}")
    if info['gpu'].get('compute_capability'):
        print(f"  Compute Cap:      {info['gpu']['compute_capability']}")
    if info['gpu'].get('driver_version'):
        print(f"  NVIDIA Driver:    {info['gpu']['driver_version']}")
    if info['gpu'].get('driver_note'):
        print(f"  Driver Status:    {info['gpu']['driver_note']}")

    if not gpus and not info['gpu'].get('model'):
        if info['gpu'].get('driver_note'):
            print(f"\n  GPU:              Detected (via lspci)")
            print(f"  Driver Status:    {info['gpu']['driver_note']}")
        else:
            print("\n  GPU:              Not detected or driver not loaded")

    # Capabilities
    caps = info['capabilities']
    vendors = info.get('gpu_vendors', [])
    print("\n  Hardware Capabilities:")
    print(f"    Vulkan:  {'[OK] Supported' if caps['vulkan_supported'] else '[--] Not available'}")
    if 'nvidia' in vendors:
        print(f"    CUDA:    {'[OK] Supported' if caps['cuda_supported'] else '[--] Not available'}")
        print(f"    NVENC:   {'[OK] Supported' if caps['nvenc_supported'] else '[--] Not available'}")
        print(f"    NVDEC:   {'[OK] Supported' if caps['nvdec_supported'] else '[--] Not available'}")
    if 'intel' in vendors:
        print(f"    QSV:     {'[OK] Supported' if caps['qsv_supported'] else '[--] Not available'}")

    # Warnings/Notes
    if not caps['vulkan_supported'] and info['gpu'].get('compute_capability'):
        print("\n  Note: Vulkan GPU compute requires Maxwell architecture or newer for NVIDIA.")

    print("\n" + "=" * 60)


def run_preliminary_checks():
    """Run all preliminary system checks.

    Only performs fast, essential gates before showing the menu:
    GPU present, OS version, dependencies, and internet.
    Performance recommendations are shown once (marker file).
    Cleanup/audit is available as a menu item.
    """
    log_step("Running preliminary system checks...")

    _show_performance_note_once()
    _check_gpu_present()
    _check_ubuntu_version()
    _install_dependencies()
    _check_internet_connectivity()


def _show_performance_note_once():
    """Show NVIDIA performance recommendations once, then remember via marker file."""
    if os.path.exists(_ACKNOWLEDGED_MARKER):
        return

    log_info("Tip: For optimal GPU performance, add kernel parameters:")
    log_info("  pcie_port_pm=off  pcie_aspm.policy=performance")
    log_info("  (Add to GRUB_CMDLINE_LINUX_DEFAULT in /etc/default/grub, then update-grub)")

    try:
        os.makedirs(os.path.dirname(_ACKNOWLEDGED_MARKER), exist_ok=True)
        with open(_ACKNOWLEDGED_MARKER, "w") as fh:
            fh.write("acknowledged\n")
    except OSError:
        pass  # Non-critical, will just show again next time


def _check_gpu_present():
    """Check if any supported GPU (NVIDIA, Intel, or AMD) is detected."""
    vendors = detect_gpu_vendors()
    if not vendors:
        log_error("No supported GPU detected (NVIDIA, Intel, or AMD).")
        if not prompt_yes_no("Continue anyway?"):
            sys.exit(1)
        return

    labels = [v.upper() for v in vendors]
    log_info(f"\u2713 GPU detected: {', '.join(labels)}")


def _offer_cleanup_option():
    """Offer to clean up old drivers, stale libraries, and NVIDIA repositories"""
    if prompt_yes_no("Would you like to scan for old NVIDIA driver versions and stale libraries?"):
        # First do a dry-run to show what would be cleaned
        log_info("Scanning for issues (dry-run)...")
        has_issues = full_nvidia_cleanup(dry_run=True)

        if has_issues:
            if prompt_yes_no("Issues found. Apply fixes now?"):
                full_nvidia_cleanup(dry_run=False)
                cleanup_nvidia_repos()
        else:
            log_info("System is clean \u2014 no old drivers or stale libraries found")
            # Still offer to clean repos
            cleanup_nvidia_repos()


def _check_ubuntu_version():
    """Check Ubuntu version compatibility"""
    SUPPORTED_VERSIONS = ["22.04", "24.04"]

    os_info = get_os_info()
    detected_name = os_info.get('NAME', '')
    detected_version = os_info.get('VERSION_ID', '')
    pretty_name = os_info.get('PRETTY_NAME', 'Unknown OS')

    if detected_name != 'Ubuntu':
        # Not Ubuntu at all (Debian, etc.)
        warning_msg = (
            f"This script is designed for Ubuntu ({', '.join(SUPPORTED_VERSIONS)}), "
            f"but detected: {pretty_name}. "
            f"It may work on Debian-based systems but is not tested."
        )
        if not prompt_yes_no(f"{warning_msg} Continue anyway?"):
            sys.exit(1)
    elif detected_version not in SUPPORTED_VERSIONS:
        # Ubuntu but unsupported version
        warning_msg = (
            f"This script supports Ubuntu {', '.join(SUPPORTED_VERSIONS)}, "
            f"but detected Ubuntu {detected_version} ({pretty_name}). "
            f"It may still work but has not been tested on this version."
        )
        if not prompt_yes_no(f"{warning_msg} Continue anyway?"):
            sys.exit(1)
    else:
        log_info(f"Ubuntu {detected_version} detected (supported)")


def _install_dependencies():
    """Install required system dependencies (skips if all present)."""
    dependencies = [
        "curl", "gnupg", "lsb-release", "ca-certificates",
        "wget", "git", "python3-pip",
    ]

    # Fast check: see if all packages are already installed
    missing: list[str] = []
    for pkg in dependencies:
        result = run_command(f"dpkg -s {pkg} 2>/dev/null | grep -q 'Status: install ok installed'",
                            capture_output=True, check=False)
        # run_command returns output; for shell one-liners we check return code via the output
        check = run_command(f"dpkg -s {pkg}", capture_output=True, check=False)
        if not check or "install ok installed" not in check:
            missing.append(pkg)

    if not missing:
        log_info("\u2713 All dependencies present")
        return

    log_info(f"Installing missing dependencies: {', '.join(missing)}")
    apt = AptManager()
    apt.install(*missing)
    log_info("\u2713 Dependencies installed")


def _check_internet_connectivity():
    """Check internet connectivity"""
    if not check_internet():
        log_error("No internet connectivity detected!")
        if not prompt_yes_no("Continue without internet?"):
            sys.exit(1)
    else:
        log_info("\u2713 Internet connectivity verified")


def detect_existing_installations():
    """Detect what's already installed on the system"""
    installations = {
        'nvidia_driver': {'installed': False, 'version': None},
        'docker': {'installed': False, 'version': None},
        'nvidia_runtime': {'installed': False, 'version': None},
        'vulkan': {'installed': False, 'version': None},
        'vulkan_sdk': {'installed': False, 'version': None},
        'cuda_toolkit': {'installed': False, 'version': None},
    }

    # Check NVIDIA driver
    try:
        nvidia_version = run_command("nvidia-smi --query-gpu=driver_version --format=csv,noheader",
                                   capture_output=True, check=False)
        error_indicators = [
            "command not found",
            "failed to initialize nvml",
            "driver/library version mismatch",
        ]
        if nvidia_version and not any(err in nvidia_version.lower() for err in error_indicators):
            installations['nvidia_driver']['installed'] = True
            installations['nvidia_driver']['version'] = nvidia_version.strip()
    except Exception:
        pass

    # Check Docker
    try:
        docker_version = run_command("docker --version", capture_output=True, check=False)
        if docker_version and "Docker version" in docker_version:
            installations['docker']['installed'] = True
            # Extract version number (e.g., "Docker version 24.0.6" -> "24.0.6")
            version_part = docker_version.split("Docker version")[1].split(",")[0].strip()
            installations['docker']['version'] = version_part
    except:
        pass

    # Check NVIDIA Container Runtime
    try:
        # Check if nvidia runtime is configured in docker
        daemon_config = "/etc/docker/daemon.json"
        if os.path.exists(daemon_config):
            with open(daemon_config, 'r') as f:
                content = f.read()
                if 'nvidia' in content.lower():
                    installations['nvidia_runtime']['installed'] = True
                    installations['nvidia_runtime']['version'] = "Configured"
    except:
        pass

    # Check Vulkan
    try:
        vulkan_output = run_command("vulkaninfo --summary 2>&1", capture_output=True, check=False)
        if vulkan_output:
            if "NVIDIA" in vulkan_output:
                installations['vulkan']['installed'] = True
                installations['vulkan']['version'] = "NVIDIA GPU"
            elif "Intel" in vulkan_output:
                installations['vulkan']['installed'] = True
                installations['vulkan']['version'] = "Intel GPU"
            elif "RADV" in vulkan_output or "AMD" in vulkan_output.upper():
                installations['vulkan']['installed'] = True
                installations['vulkan']['version'] = "AMD GPU"
            elif "llvmpipe" in vulkan_output.lower():
                installations['vulkan']['installed'] = True
                installations['vulkan']['version'] = "Software only"
            elif "Vulkan Instance Version" in vulkan_output:
                installations['vulkan']['installed'] = True
                installations['vulkan']['version'] = "Available"
    except Exception:
        pass

    # Check Vulkan SDK (LunarG development SDK)
    # 1. Tarball install at /opt/vulkan-sdk/ (current method)
    _vulkan_sdk_base = "/opt/vulkan-sdk"
    _vulkan_current = os.path.join(_vulkan_sdk_base, "current")
    if os.path.islink(_vulkan_current):
        target = os.path.basename(os.readlink(_vulkan_current))
        if re.match(r"\d+\.\d+\.\d+", target):
            installations['vulkan_sdk']['installed'] = True
            installations['vulkan_sdk']['version'] = target
    if not installations['vulkan_sdk']['installed'] and os.path.isdir(_vulkan_sdk_base):
        try:
            dirs = [
                e.name for e in os.scandir(_vulkan_sdk_base)
                if e.is_dir() and re.match(r"\d+\.\d+\.\d+", e.name)
            ]
            if dirs:
                dirs.sort(key=lambda v: [int(x) for x in v.split(".")[:3]], reverse=True)
                installations['vulkan_sdk']['installed'] = True
                installations['vulkan_sdk']['version'] = dirs[0]
        except OSError:
            pass
    # 2. Legacy APT install
    if not installations['vulkan_sdk']['installed']:
        try:
            sdk_output = run_command(
                "dpkg -s vulkan-sdk 2>/dev/null | grep '^Version:'",
                capture_output=True, check=False,
            )
            if sdk_output and "Version:" in sdk_output:
                installations['vulkan_sdk']['installed'] = True
                installations['vulkan_sdk']['version'] = sdk_output.split("Version:")[1].strip()
        except Exception:
            pass
    # 3. VULKAN_SDK environment variable
    if not installations['vulkan_sdk']['installed']:
        sdk_path = os.environ.get("VULKAN_SDK")
        if sdk_path and os.path.isdir(sdk_path):
            installations['vulkan_sdk']['installed'] = True
            installations['vulkan_sdk']['version'] = "Installed"

    # Check CUDA Toolkit (host nvcc)
    # 1. Try nvcc on PATH
    try:
        nvcc_output = run_command("nvcc --version 2>/dev/null", capture_output=True, check=False)
        if nvcc_output and "release" in nvcc_output.lower():
            match = re.search(r"release\s+([\d.]+)", nvcc_output)
            if match:
                installations['cuda_toolkit']['installed'] = True
                installations['cuda_toolkit']['version'] = match.group(1)
    except Exception:
        pass
    # 2. Fallback: nvcc may not be on PATH yet (profile.d not sourced)
    if not installations['cuda_toolkit']['installed']:
        try:
            nvcc_output = run_command(
                "/usr/local/cuda/bin/nvcc --version 2>/dev/null",
                capture_output=True, check=False,
            )
            if nvcc_output and "release" in nvcc_output.lower():
                match = re.search(r"release\s+([\d.]+)", nvcc_output)
                if match:
                    installations['cuda_toolkit']['installed'] = True
                    installations['cuda_toolkit']['version'] = match.group(1)
        except Exception:
            pass
    # 3. Fallback: version.json in /usr/local/cuda
    if not installations['cuda_toolkit']['installed']:
        import json as _json
        version_json = "/usr/local/cuda/version.json"
        if os.path.exists(version_json):
            try:
                with open(version_json, "r") as fh:
                    data = _json.load(fh)
                ver = data.get("cuda", {}).get("version")
                if ver:
                    installations['cuda_toolkit']['installed'] = True
                    installations['cuda_toolkit']['version'] = ver
            except Exception:
                pass

    return installations


def check_gpu_capabilities():
    """Check GPU capabilities for media processing"""
    log_step("Checking GPU capabilities for media processing...")

    try:
        # Get GPU model
        gpu_model = run_command(
            "nvidia-smi --query-gpu=gpu_name --format=csv,noheader",
            capture_output=True
        )
        log_info(f"Detected GPU: {gpu_model}")

        # Get compute capability
        compute_cap = run_command(
            "nvidia-smi --query-gpu=compute_cap --format=csv,noheader",
            capture_output=True
        )
        log_info(f"GPU Architecture: Compute {compute_cap}")

        # Check NVENC/NVDEC support
        nvidia_info = run_command("nvidia-smi -q", capture_output=True)

        if "Encoder" in nvidia_info:
            log_info("\u2713 NVENC (GPU encoding) is supported")
            log_info("  \u2192 Compatible with FFmpeg GPU acceleration")
            log_info("  \u2192 Compatible with Plex GPU-accelerated encoding")
        else:
            log_warn("\u2717 NVENC not detected - GPU encoding may not be available")

        if "Decoder" in nvidia_info:
            log_info("\u2713 NVDEC (GPU decoding) is supported")
            log_info("  \u2192 Compatible with FFmpeg GPU acceleration")
            log_info("  \u2192 Compatible with Plex GPU-accelerated decoding")
        else:
            log_warn("\u2717 NVDEC not detected - GPU decoding may not be available")

        # GPU model specific guidance
        _provide_gpu_guidance(gpu_model)

    except Exception as e:
        log_warn(f"Cannot check GPU model - driver might not be loaded yet: {e}")


def _provide_gpu_guidance(gpu_model):
    """Provide guidance based on GPU model"""
    if not gpu_model:
        return

    gpu_lower = gpu_model.lower()

    if any(x in gpu_lower for x in ["rtx 40", "rtx 50"]):
        log_info("\u2713 Modern GPU detected - excellent performance expected")
        log_info("  \u2192 Full support for AV1, H.265/HEVC, H.264/AVC")
    elif "rtx 30" in gpu_lower:
        log_info("\u2713 Very good GPU model - well-supported")
        log_info("  \u2192 Good support for H.265/HEVC, H.264/AVC")
    elif any(x in gpu_lower for x in ["rtx 20", "gtx 16"]):
        log_info("\u2713 Good GPU model - well-supported")
        log_info("  \u2192 Supports H.265/HEVC, H.264/AVC")
    else:
        log_info("\u2713 GPU detected - compatibility may vary")
        log_info("  \u2192 Check NVIDIA documentation for codec support")

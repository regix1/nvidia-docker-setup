"""System checks and validation"""

import sys
from utils.logging import log_info, log_warn, log_error, log_step
from utils.prompts import prompt_yes_no, prompt_acknowledge
from utils.system import run_command, AptManager, cleanup_nvidia_repos, check_internet, get_os_info, check_nvidia_gpu


def run_preliminary_checks():
    """Run all preliminary system checks"""
    log_step("Running preliminary system checks...")
    
    _display_performance_recommendations()
    _check_nvidia_gpu_present()
    _offer_cleanup_option()
    _check_ubuntu_version()
    _install_dependencies()
    _check_internet_connectivity()


def _display_performance_recommendations():
    """Display NVIDIA performance recommendations"""
    log_step("IMPORTANT: NVIDIA Performance Recommendations")
    
    recommendations = """
For optimal NVIDIA GPU performance and reliability in Docker containers,
the following kernel parameters are highly recommended:

pcie_port_pm=off                    - Disables PCIe power management for better performance
pcie_aspm.policy=performance        - Sets PCIe power state policy to performance mode

IMPORTANT: If using GPU passthrough to a VM, these parameters should be
added to the GRUB configuration on the BARE METAL HOST, not in the VM.

To add these parameters to your GRUB configuration:
1. Edit /etc/default/grub
2. Add these parameters to GRUB_CMDLINE_LINUX_DEFAULT:
   Example: GRUB_CMDLINE_LINUX_DEFAULT="quiet splash pcie_port_pm=off pcie_aspm.policy=performance"
3. Run update-grub (or proxmox-boot-tool refresh on Proxmox)
4. Reboot your system
"""
    
    print(recommendations)
    prompt_acknowledge(
        "Please read the performance recommendations above carefully.",
        "I understand"
    )


def _check_nvidia_gpu_present():
    """Check if NVIDIA GPU is detected"""
    if not check_nvidia_gpu():
        log_error("No NVIDIA GPU detected! This script requires an NVIDIA GPU.")
        sys.exit(1)
    
    log_info("✓ NVIDIA GPU detected")


def _offer_cleanup_option():
    """Offer to clean up existing NVIDIA repositories"""
    if prompt_yes_no("Would you like to clean up existing NVIDIA repositories and fix any driver mismatches?"):
        cleanup_nvidia_repos()


def _check_ubuntu_version():
    """Check Ubuntu version compatibility"""
    EXPECTED_VERSION = "22.04"
    
    os_info = get_os_info()
    
    if os_info.get('NAME') != 'Ubuntu' or os_info.get('VERSION_ID') != EXPECTED_VERSION:
        pretty_name = os_info.get('PRETTY_NAME', 'Unknown OS')
        warning_msg = f"This script is designed for Ubuntu {EXPECTED_VERSION}, but detected: {pretty_name}"
        
        if not prompt_yes_no(f"{warning_msg}. Continue anyway?"):
            sys.exit(1)
    else:
        log_info(f"✓ Ubuntu {EXPECTED_VERSION} detected")


def _install_dependencies():
    """Install required system dependencies"""
    log_info("Installing required dependencies...")
    
    apt = AptManager()
    dependencies = [
        "curl", "gnupg", "lsb-release", "ca-certificates", 
        "wget", "git", "python3-pip"
    ]
    
    apt.install(*dependencies)
    log_info("✓ Dependencies installed")


def _check_internet_connectivity():
    """Check internet connectivity"""
    if not check_internet():
        log_error("No internet connectivity detected!")
        if not prompt_yes_no("Continue without internet?"):
            sys.exit(1)
    else:
        log_info("✓ Internet connectivity verified")


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
            log_info("✓ NVENC (GPU encoding) is supported")
            log_info("  → Compatible with FFmpeg GPU acceleration")
            log_info("  → Compatible with Plex GPU-accelerated encoding")
        else:
            log_warn("✗ NVENC not detected - GPU encoding may not be available")
        
        if "Decoder" in nvidia_info:
            log_info("✓ NVDEC (GPU decoding) is supported")
            log_info("  → Compatible with FFmpeg GPU acceleration")
            log_info("  → Compatible with Plex GPU-accelerated decoding")
        else:
            log_warn("✗ NVDEC not detected - GPU decoding may not be available")
        
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
        log_info("✓ Modern GPU detected - excellent performance expected")
        log_info("  → Full support for AV1, H.265/HEVC, H.264/AVC")
    elif "rtx 30" in gpu_lower:
        log_info("✓ Very good GPU model - well-supported")
        log_info("  → Good support for H.265/HEVC, H.264/AVC")
    elif any(x in gpu_lower for x in ["rtx 20", "gtx 16"]):
        log_info("✓ Good GPU model - well-supported")
        log_info("  → Supports H.265/HEVC, H.264/AVC")
    else:
        log_info("✓ GPU detected - compatibility may vary")
        log_info("  → Check NVIDIA documentation for codec support")
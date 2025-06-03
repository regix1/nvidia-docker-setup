"""NVIDIA driver management"""

import subprocess
from utils.logging import log_info, log_warn, log_error, log_step
from utils.prompts import prompt_yes_no, prompt_input
from utils.system import run_command, AptManager


def select_nvidia_driver():
    """Select and install NVIDIA driver"""
    log_step("Selecting NVIDIA driver version...")
    
    # Check if drivers are already installed
    if _check_existing_driver():
        if not prompt_yes_no("NVIDIA driver is already installed. Would you like to reinstall/update it?"):
            return
    
    _install_driver_prerequisites()
    _detect_hardware()
    
    recommended_version = _get_recommended_driver()
    
    if prompt_yes_no("Install recommended NVIDIA driver automatically?"):
        _install_automatic_driver(recommended_version)
    else:
        _install_manual_driver(recommended_version)
    
    _post_install_checks()


def _check_existing_driver():
    """Check if NVIDIA drivers are already installed"""
    try:
        nvidia_smi_output = run_command("nvidia-smi", capture_output=True, check=False)
        if nvidia_smi_output:
            log_info("Current NVIDIA installation:")
            print(nvidia_smi_output)
            return True
    except:
        pass
    
    return False


def _install_driver_prerequisites():
    """Install prerequisites for driver installation"""
    log_info("Installing driver prerequisites...")
    
    apt = AptManager()
    prerequisites = [
        "build-essential",
        "dkms", 
        f"linux-headers-{_get_kernel_version()}",
        "ubuntu-drivers-common",
        "pkg-config",
        "libglvnd-dev"
    ]
    
    apt.install(*prerequisites)


def _get_kernel_version():
    """Get current kernel version"""
    return run_command("uname -r", capture_output=True)


def _detect_hardware():
    """Detect NVIDIA hardware"""
    log_info("Detecting NVIDIA hardware...")
    try:
        output = run_command("ubuntu-drivers devices | grep -i nvidia", capture_output=True)
        if output:
            print(output)
    except:
        log_warn("Could not detect NVIDIA hardware details")


def _get_recommended_driver():
    """Get recommended driver version"""
    try:
        output = run_command(
            "ubuntu-drivers devices | grep 'recommended' | grep -oP 'nvidia-driver-\\K[0-9]+' | head -1",
            capture_output=True,
            check=False
        )
        
        if output and output.isdigit():
            recommended = output.strip()
            log_info(f"Recommended driver version: {recommended}")
            return recommended
    except:
        pass
    
    # Default fallback
    recommended = "550"
    log_info(f"Using default driver version: {recommended}")
    return recommended


def _install_automatic_driver(recommended_version):
    """Install driver automatically"""
    log_info("Installing recommended driver using ubuntu-drivers...")
    
    try:
        run_command("ubuntu-drivers autoinstall")
        log_info("✓ Automatic driver installation completed")
    except subprocess.CalledProcessError:
        log_warn("Autoinstall failed, attempting manual installation...")
        _install_specific_driver(recommended_version)


def _install_manual_driver(recommended_version):
    """Install driver manually with user selection"""
    # Show available drivers
    log_info("Finding available driver versions...")
    try:
        available_output = run_command(
            "apt-cache search nvidia-driver- | grep '^nvidia-driver-[0-9]' | grep -v 'Transitional package' | sort -V",
            capture_output=True
        )
        if available_output:
            log_info("Available NVIDIA driver versions:")
            print(available_output)
    except:
        log_warn("Could not list available drivers")
    
    # Get user selection
    driver_version = prompt_input(
        f"Enter desired driver version number",
        default=recommended_version
    )
    
    if not driver_version:
        log_error("No driver version specified!")
        return
    
    _install_specific_driver(driver_version)


def _install_specific_driver(version):
    """Install specific driver version"""
    package_name = f"nvidia-driver-{version}"
    log_info(f"Installing NVIDIA driver version {version}...")
    
    try:
        apt = AptManager()
        apt.install(package_name)
        log_info(f"✓ Successfully installed {package_name}")
    except subprocess.CalledProcessError:
        log_error(f"Failed to install {package_name}")
        raise


def _post_install_checks():
    """Post-installation checks and module loading"""
    # Try to load nvidia module
    try:
        run_command("modprobe nvidia", check=False)
    except:
        log_warn("Could not load nvidia module (normal before reboot)")
    
    # Check if nvidia-smi works
    try:
        nvidia_smi_output = run_command("nvidia-smi", capture_output=True, check=False)
        if nvidia_smi_output and "NVIDIA-SMI" in nvidia_smi_output:
            log_info("✓ NVIDIA drivers successfully installed!")
            print(nvidia_smi_output)
        else:
            log_warn("nvidia-smi not working yet - you may need to reboot")
    except:
        log_warn("nvidia-smi not working yet - you may need to reboot")
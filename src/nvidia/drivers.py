"""NVIDIA driver management with enhanced version selection"""

import subprocess
from utils.logging import log_info, log_warn, log_error, log_step
from utils.prompts import prompt_yes_no, prompt_input, prompt_choice
from utils.system import run_command, AptManager


def select_nvidia_driver():
    """Select and install NVIDIA driver"""
    log_step("Selecting NVIDIA driver version...")
    
    # Check if drivers are already installed
    current_driver = _check_existing_driver()
    if current_driver:
        _handle_existing_driver(current_driver)
    else:
        _install_new_driver()
    
    _post_install_checks()


def _check_existing_driver():
    """Check if NVIDIA drivers are already installed and return version"""
    try:
        nvidia_smi_output = run_command("nvidia-smi --query-gpu=driver_version --format=csv,noheader", capture_output=True, check=False)
        if nvidia_smi_output:
            current_version = nvidia_smi_output.strip()
            log_info(f"Current NVIDIA driver version: {current_version}")
            
            # Also show nvidia-smi output for full info
            full_output = run_command("nvidia-smi", capture_output=True, check=False)
            if full_output:
                print("\nCurrent NVIDIA installation:")
                print(full_output)
            
            return current_version
    except:
        pass
    
    return None


def _handle_existing_driver(current_version):
    """Handle existing driver installation with options"""
    log_info(f"NVIDIA driver {current_version} is already installed.")
    
    # Get recommended and available versions
    recommended_version = _get_recommended_driver()
    latest_available = _get_latest_available_driver()
    
    print("\nDriver Management Options:")
    options = [
        f"Keep current driver ({current_version})",
        f"Reinstall current driver ({current_version})",
    ]
    
    # Add update option if newer version available
    if recommended_version and recommended_version != current_version:
        options.append(f"Update to recommended version ({recommended_version})")
    
    if latest_available and latest_available != current_version and latest_available != recommended_version:
        options.append(f"Update to latest available ({latest_available})")
    
    options.extend([
        "Choose specific version",
        "Show available versions & compatibility info"
    ])
    
    for i, option in enumerate(options, 1):
        print(f"  {i}. {option}")
    
    choice_idx = prompt_choice(
        "Select option",
        [f"Option {i}" for i in range(1, len(options) + 1)],
        default=0
    )
    
    if choice_idx == 0:  # Keep current
        log_info("Keeping current driver installation")
        return
    elif choice_idx == 1:  # Reinstall current
        log_info(f"Reinstalling driver version {current_version}")
        _install_specific_driver(current_version)
    elif choice_idx == 2 and recommended_version != current_version:  # Update to recommended
        log_info(f"Updating to recommended version {recommended_version}")
        if _confirm_driver_change(current_version, recommended_version):
            _install_specific_driver(recommended_version)
    elif choice_idx == 3 and latest_available != current_version:  # Update to latest
        log_info(f"Updating to latest version {latest_available}")
        if _confirm_driver_change(current_version, latest_available):
            _install_specific_driver(latest_available)
    elif choice_idx == len(options) - 2:  # Choose specific
        _install_manual_driver(current_version)
    elif choice_idx == len(options) - 1:  # Show available
        _show_available_drivers()
        _handle_existing_driver(current_version)  # Show options again
    else:
        log_info("Keeping current driver")


def _confirm_driver_change(current_version, new_version):
    """Confirm driver version change with compatibility info"""
    print(f"\nDriver Change Summary:")
    print(f"  Current: {current_version}")
    print(f"  New:     {new_version}")
    
    # Show CUDA compatibility
    current_cuda = _get_cuda_support(current_version)
    new_cuda = _get_cuda_support(new_version)
    
    if current_cuda:
        print(f"  Current CUDA support: {', '.join(current_cuda[:3])}...")
    if new_cuda:
        print(f"  New CUDA support:     {', '.join(new_cuda[:3])}...")
    
    return prompt_yes_no("Proceed with driver change?")


def _install_new_driver():
    """Install driver on system without existing installation"""
    log_info("No NVIDIA driver detected. Installing new driver...")
    
    _install_driver_prerequisites()
    _detect_hardware()
    
    recommended_version = _get_recommended_driver()
    
    if prompt_yes_no(f"Install recommended NVIDIA driver ({recommended_version}) automatically?"):
        _install_automatic_driver(recommended_version)
    else:
        _install_manual_driver(recommended_version)


def _show_available_drivers():
    """Display available driver versions with compatibility info"""
    log_info("Finding available driver versions...")
    
    try:
        available_output = run_command(
            "apt-cache search nvidia-driver- | grep '^nvidia-driver-[0-9]' | grep -v 'Transitional package' | sort -V",
            capture_output=True
        )
        if available_output:
            print("\nAvailable NVIDIA driver versions:")
            print(available_output)
            
            _show_driver_compatibility_info()
    except:
        log_warn("Could not list available drivers")


def _show_driver_compatibility_info():
    """Show comprehensive compatibility information"""
    info = """
╔══════════════════════════════════════════════════════════════╗
║                    Driver Compatibility Guide               ║
╚══════════════════════════════════════════════════════════════╝

Driver Series Overview:
• 565.x series: Latest features, RTX 40 series optimized, CUDA 12.4+ support
• 560.x series: Stable release, good compatibility, CUDA 12.3+ support  
• 550.x series: LTS candidate, enterprise ready, CUDA 12.2+ support
• 535.x series: Previous LTS, mature and stable, CUDA 12.0+ support
• 525.x series: Legacy stable, broad compatibility, CUDA 11.8+ support

Hardware Recommendations:
• RTX 40 series (4090, 4080, etc.): Use 565.x or newer
• RTX 30 series (3090, 3080, etc.): Use 550.x or newer  
• RTX 20 series (2080, 2070, etc.): Use 535.x or newer
• GTX 16/10 series: Use 525.x or newer for best compatibility

Usage Recommendations:
• Gaming/Latest features: Use newest available (565.x+)
• Production/Stability: Use LTS versions (535.x, 550.x)
• Container workloads: Match with intended CUDA version
• Older hardware: Consider 525.x or 470.x series

CUDA Version Support:
• Driver 565.x+: CUDA 12.4, 12.3, 12.2, 12.1, 12.0, 11.8
• Driver 550.x+: CUDA 12.2, 12.1, 12.0, 11.8, 11.7  
• Driver 535.x+: CUDA 12.0, 11.8, 11.7, 11.6
• Driver 525.x+: CUDA 11.8, 11.7, 11.6, 11.5
"""
    print(info)


def _get_cuda_support(driver_version):
    """Get supported CUDA versions for a driver version"""
    # Extract major version number
    try:
        major_version = int(driver_version.split('.')[0])
    except:
        return []
    
    cuda_support = {
        565: ["12.4.0", "12.3.2", "12.2.2", "12.1.1", "12.0.1", "11.8.0"],
        560: ["12.3.2", "12.2.2", "12.1.1", "12.0.1", "11.8.0", "11.7.1"],
        550: ["12.2.2", "12.1.1", "12.0.1", "11.8.0", "11.7.1", "11.6.2"],
        535: ["12.0.1", "11.8.0", "11.7.1", "11.6.2"],
        525: ["11.8.0", "11.7.1", "11.6.2"],
        470: ["11.7.1", "11.6.2", "11.5.2"]
    }
    
    # Find the best match
    for version_threshold in sorted(cuda_support.keys(), reverse=True):
        if major_version >= version_threshold:
            return cuda_support[version_threshold]
    
    return ["11.6.2"]  # Fallback for older drivers


def _get_recommended_driver():
    """Get recommended driver version with better detection"""
    try:
        # Try to get Ubuntu's recommendation first
        output = run_command(
            "ubuntu-drivers devices | grep 'recommended' | grep -oP 'nvidia-driver-\\K[0-9]+' | head -1",
            capture_output=True,
            check=False
        )
        
        if output and output.strip().isdigit():
            recommended = output.strip()
            log_info(f"Ubuntu recommends driver version: {recommended}")
            return recommended
    except:
        pass
    
    # Fall back to latest available
    latest = _get_latest_available_driver()
    if latest:
        return latest
    
    # Ultimate fallback
    return "565"


def _get_latest_available_driver():
    """Get the latest available driver version"""
    try:
        latest_output = run_command(
            "apt-cache search nvidia-driver- | grep '^nvidia-driver-[0-9]' | grep -v 'Transitional' | sort -V | tail -1 | grep -oP 'nvidia-driver-\\K[0-9]+'",
            capture_output=True,
            check=False
        )
        if latest_output:
            return latest_output.strip()
    except:
        pass
    
    return None


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
        "libglvnd-dev",
        # Vulkan prerequisites
        "libvulkan1",
        "vulkan-tools",
    ]

    apt.install(*prerequisites)


def _get_kernel_version():
    """Get current kernel version"""
    return run_command("uname -r", capture_output=True).strip()


def _detect_hardware():
    """Detect NVIDIA hardware"""
    log_info("Detecting NVIDIA hardware...")
    try:
        output = run_command("ubuntu-drivers devices | grep -i nvidia", capture_output=True)
        if output:
            print("Detected NVIDIA hardware:")
            print(output)
        
        # Also try lspci for more details
        pci_output = run_command("lspci | grep -i nvidia", capture_output=True, check=False)
        if pci_output:
            print("\nPCI devices:")
            print(pci_output)
            
    except:
        log_warn("Could not detect NVIDIA hardware details")


def _install_automatic_driver(recommended_version):
    """Install driver automatically"""
    log_info("Installing recommended driver using ubuntu-drivers...")
    
    try:
        run_command("ubuntu-drivers autoinstall")
        log_info("✓ Automatic driver installation completed")
    except subprocess.CalledProcessError:
        log_warn("Autoinstall failed, attempting manual installation...")
        _install_specific_driver(recommended_version)


def _install_manual_driver(current_version=None):
    """Install driver manually with user selection"""
    # Show available drivers first
    _show_available_drivers()
    
    # Get recommended version
    recommended_version = _get_recommended_driver()
    
    # Get user selection
    driver_version = prompt_input(
        f"Enter desired driver version number (recommended: {recommended_version})",
        default=recommended_version
    )
    
    if not driver_version:
        log_error("No driver version specified!")
        return
    
    # Show what CUDA versions this driver supports
    cuda_versions = _get_cuda_support(driver_version)
    if cuda_versions:
        log_info(f"Driver {driver_version} supports CUDA versions: {', '.join(cuda_versions[:5])}")
    
    _install_specific_driver(driver_version)


def _install_specific_driver(version):
    """Install specific driver version"""
    package_name = f"nvidia-driver-{version}"
    log_info(f"Installing NVIDIA driver version {version}...")

    try:
        apt = AptManager()
        apt.install(package_name)
        log_info(f"Successfully installed {package_name}")

        # Also install libnvidia-gl for Vulkan support
        gl_package = f"libnvidia-gl-{version}"
        log_info(f"Installing Vulkan/OpenGL support: {gl_package}")
        try:
            apt.install(gl_package)
            log_info(f"Successfully installed {gl_package}")
        except:
            log_warn(f"Could not install {gl_package} - Vulkan may not work properly")

    except subprocess.CalledProcessError:
        log_error(f"Failed to install {package_name}")

        # Try alternative package names
        alternatives = [
            f"nvidia-driver-{version}-server",
            f"nvidia-{version}",
        ]

        for alt_package in alternatives:
            try:
                log_info(f"Trying alternative package: {alt_package}")
                apt.install(alt_package)
                log_info(f"Successfully installed {alt_package}")
                return
            except:
                continue

        raise Exception(f"Could not install driver version {version}")


def _post_install_checks():
    """Post-installation checks and module loading"""
    log_step("Performing post-installation checks...")

    # Try to load nvidia module
    try:
        run_command("modprobe nvidia", check=False)
        log_info("NVIDIA kernel module loaded")
    except:
        log_warn("Could not load nvidia module (normal before reboot)")

    # Check if nvidia-smi works
    try:
        nvidia_smi_output = run_command("nvidia-smi", capture_output=True, check=False)
        if nvidia_smi_output and "NVIDIA-SMI" in nvidia_smi_output:
            log_info("NVIDIA drivers successfully installed and working!")
            print("\nNVIDIA System Information:")
            print(nvidia_smi_output)

            # Extract and display key info
            _display_driver_summary(nvidia_smi_output)
        else:
            log_warn("nvidia-smi not working yet - reboot required")
    except:
        log_warn("nvidia-smi not working yet - reboot required")

    # Check for common issues
    _check_common_issues()

    # Check Vulkan support
    _check_vulkan_support()


def _check_vulkan_support():
    """Check if Vulkan is working with NVIDIA"""
    log_info("Checking Vulkan support...")

    try:
        output = run_command("vulkaninfo --summary 2>&1", capture_output=True, check=False)
        if output:
            if "NVIDIA" in output:
                log_info("Vulkan detected NVIDIA GPU")
            elif "llvmpipe" in output.lower():
                log_warn("Vulkan only detected software renderer (llvmpipe)")
                log_info("NVIDIA Vulkan may work after reboot")
            else:
                log_info("Vulkan available - check GPU detection after reboot")
    except:
        log_info("vulkan-tools not available or Vulkan not working yet")


def _display_driver_summary(nvidia_smi_output):
    """Display a summary of the installed driver"""
    try:
        lines = nvidia_smi_output.split('\n')
        driver_line = next((line for line in lines if "Driver Version:" in line), None)
        cuda_line = next((line for line in lines if "CUDA Version:" in line), None)
        
        if driver_line:
            driver_version = driver_line.split("Driver Version:")[1].split()[0]
            cuda_version = cuda_line.split("CUDA Version:")[1].split()[0] if cuda_line else "N/A"
            
            print(f"\n╔══════════════════════════════════════════════════════════════╗")
            print(f"║                    Installation Summary                     ║")
            print(f"╠══════════════════════════════════════════════════════════════╣")
            print(f"║ Driver Version: {driver_version:<44} ║")
            print(f"║ CUDA Version:   {cuda_version:<44} ║")
            print(f"╚══════════════════════════════════════════════════════════════╝")
            
    except:
        pass


def _check_common_issues():
    """Check for common driver installation issues"""
    log_info("Checking for common issues...")
    
    # Check for secure boot
    try:
        mokutil_output = run_command("mokutil --sb-state", capture_output=True, check=False)
        if mokutil_output and "SecureBoot enabled" in mokutil_output:
            log_warn("Secure Boot is enabled - you may need to disable it or sign the driver")
    except:
        pass
    
    # Check for conflicting packages
    try:
        nouveau_check = run_command("lsmod | grep nouveau", capture_output=True, check=False)
        if nouveau_check:
            log_warn("Nouveau driver detected - may conflict with NVIDIA driver")
            log_info("Consider blacklisting nouveau if you experience issues")
    except:
        pass


def show_driver_info():
    """Display comprehensive information about NVIDIA drivers"""
    info = """
╔══════════════════════════════════════════════════════════════╗
║                   NVIDIA Driver Information                 ║
╚══════════════════════════════════════════════════════════════╝

NVIDIA drivers provide the interface between your GPU hardware and
the operating system, enabling GPU acceleration for applications.

Key Components:
• Kernel driver: Low-level hardware interface
• User-space libraries: CUDA, OpenGL, Vulkan support
• NVIDIA-SMI: System management interface
• NVML: NVIDIA Management Library

Installation Types:
• ubuntu-drivers autoinstall: Automatic recommended driver
• Manual selection: Choose specific version for your needs
• Repository packages: Standard Ubuntu/PPA packages
• Official installer: Direct from NVIDIA (not recommended)

After Installation:
• Reboot required for kernel driver loading
• Test with: nvidia-smi
• Verify CUDA: nvidia-smi | grep CUDA
• Check processes: nvidia-smi -q -d PIDS

Troubleshooting:
• Driver not loading: Check secure boot, conflicting drivers
• Performance issues: Verify power management settings
• Application issues: Check library paths and versions
• Multiple GPUs: Verify all devices are detected

For Docker integration, ensure nvidia-container-toolkit is installed
and configured after driver installation.
"""
    
    print(info)
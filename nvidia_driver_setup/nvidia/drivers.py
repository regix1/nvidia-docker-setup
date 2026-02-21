"""NVIDIA driver management with enhanced version selection"""

import glob
import os
import re
import subprocess
from ..utils.logging import log_info, log_warn, log_error, log_step
from ..utils.prompts import prompt_yes_no, prompt_input, prompt_choice
from ..utils.system import run_command, AptManager, cleanup_stale_nvidia_libraries, repair_nvidia_symlinks

# Regex that matches a valid NVIDIA driver version string (e.g. 580.126.09 or 590)
_VERSION_PATTERN = re.compile(r'^[0-9]+\.[0-9]+')
_VERSION_MAJOR = re.compile(r'^[0-9]+$')


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


def _is_valid_version(text: str) -> bool:
    """Check if text looks like a valid NVIDIA driver version"""
    return bool(_VERSION_PATTERN.match(text.strip()))


def _detect_driver_version_fallback() -> str | None:
    """Detect driver version when nvidia-smi is broken.

    Tries: library filename, modinfo, dpkg (in order).
    Returns version string or None.
    """
    # Method 1: Parse from libnvidia-encode.so filename (pick highest version)
    all_lib_versions: list[str] = []
    for search_dir in ["/usr/lib/x86_64-linux-gnu", "/usr/lib64", "/usr/lib"]:
        pattern = os.path.join(search_dir, "libnvidia-encode.so.*.*.*")
        for path in glob.glob(pattern):
            ver_match = re.search(r'\.so\.([0-9]+\.[0-9]+\.[0-9]+)', os.path.basename(path))
            if ver_match:
                all_lib_versions.append(ver_match.group(1))
    if all_lib_versions:
        # Sort by version tuple to pick the highest installed version
        all_lib_versions.sort(key=lambda v: tuple(int(x) for x in v.split('.')), reverse=True)
        return all_lib_versions[0]

    # Method 2: modinfo nvidia
    try:
        result = subprocess.run("modinfo nvidia", shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("version:"):
                    ver = line.split(None, 1)[1].strip() if len(line.split(None, 1)) > 1 else ""
                    if ver and _VERSION_PATTERN.match(ver):
                        return ver
    except OSError:
        pass

    # Method 3: dpkg
    try:
        result = subprocess.run("dpkg -l 'nvidia-driver-*'", shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[0] == "ii" and re.match(r'^nvidia-driver-[0-9]+$', parts[1]):
                    ver_match = re.match(r'^[0-9]+\.[0-9]+\.[0-9]+', parts[2])
                    if ver_match:
                        return ver_match.group(0)
    except OSError:
        pass

    return None


def _check_existing_driver() -> str | None:
    """Check if NVIDIA drivers are already installed and return version.

    Validates nvidia-smi output is a real version string.
    Falls back to library/modinfo/dpkg detection on mismatch.
    """
    version = None
    needs_reboot = False

    # Try nvidia-smi first
    try:
        nvidia_smi_output = run_command(
            "nvidia-smi --query-gpu=driver_version --format=csv,noheader",
            capture_output=True, check=False
        )
        if nvidia_smi_output and _is_valid_version(nvidia_smi_output):
            version = nvidia_smi_output.strip()
        elif nvidia_smi_output and "mismatch" in nvidia_smi_output.lower():
            needs_reboot = True
    except Exception:
        pass

    # Fallback detection if nvidia-smi failed
    if version is None:
        version = _detect_driver_version_fallback()
        if version is not None and not needs_reboot:
            # Driver is installed but nvidia-smi didn't work
            needs_reboot = True

    if version is None:
        return None

    log_info(f"Current NVIDIA driver version: {version}")
    if needs_reboot:
        log_warn("Driver/library version mismatch - a reboot is required to use the new driver")
        log_warn("nvidia-smi will not work until you reboot")

    # Show nvidia-smi output only if it works
    if not needs_reboot:
        full_output = run_command("nvidia-smi", capture_output=True, check=False)
        if full_output and "NVIDIA-SMI" in full_output:
            print("\nCurrent NVIDIA installation:")
            print(full_output)

    return version


def _major_version(version: str) -> str:
    """Extract major version number from a full version string.

    '590.48.01' -> '590', '590' -> '590'
    """
    return version.split('.')[0]


def _handle_existing_driver(current_version: str) -> None:
    """Handle existing driver installation with options"""
    current_major = _major_version(current_version)
    log_info(f"NVIDIA driver {current_version} is already installed.")

    # Get recommended and available versions (these are major-only like '590')
    recommended_version = _get_recommended_driver()
    latest_available = _get_latest_available_driver()

    print("\nDriver Management Options:")
    options = [
        f"Keep current driver ({current_version})",
        f"Reinstall current driver ({current_major})",
    ]

    # Add update option if newer version available
    if recommended_version and recommended_version != current_major:
        options.append(f"Update to recommended version ({recommended_version})")

    if latest_available and latest_available != current_major and latest_available != recommended_version:
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
        log_info(f"Reinstalling driver version {current_major}")
        _install_specific_driver(current_major)
    elif choice_idx == 2 and recommended_version != current_major:  # Update to recommended
        log_info(f"Updating to recommended version {recommended_version}")
        if _confirm_driver_change(current_version, recommended_version):
            _install_specific_driver(recommended_version)
    elif choice_idx == 3 and latest_available != current_major:  # Update to latest
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
• 590.x series: Newest features, RTX 50 series optimized, CUDA 13.0+ support
• 580.x series: Latest stable, RTX 50/40 series optimized, CUDA 13.0+ support
• 570.x series: Recent stable, RTX 40 series optimized, CUDA 12.8+ support
• 565.x series: Stable release, RTX 40 series optimized, CUDA 12.4+ support
• 560.x series: Stable release, good compatibility, CUDA 12.3+ support
• 550.x series: LTS candidate, enterprise ready, CUDA 12.2+ support
• 535.x series: Previous LTS, mature and stable, CUDA 12.0+ support
• 525.x series: Legacy stable, broad compatibility, CUDA 11.8+ support

Hardware Recommendations:
• RTX 50 series (5090, 5080, etc.): Use 580.x or newer
• RTX 40 series (4090, 4080, etc.): Use 565.x or newer
• RTX 30 series (3090, 3080, etc.): Use 550.x or newer
• RTX 20 series (2080, 2070, etc.): Use 535.x or newer
• GTX 16/10 series: Use 525.x or newer for best compatibility

Usage Recommendations:
• Gaming/Latest features: Use newest available (580.x+)
• Production/Stability: Use LTS versions (535.x, 550.x)
• Container workloads: Match with intended CUDA version
• Older hardware: Consider 525.x or 470.x series

CUDA Version Support:
• Driver 590.x+: CUDA 13.0, 12.4, 12.3, 12.2, 12.1, 12.0, 11.8
• Driver 580.x+: CUDA 13.0, 12.4, 12.3, 12.2, 12.1, 12.0, 11.8
• Driver 570.x+: CUDA 12.8, 12.4, 12.3, 12.2, 12.1, 12.0, 11.8
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
        590: ["13.0.0", "12.4.0", "12.3.2", "12.2.2", "12.1.1", "12.0.1", "11.8.0"],
        580: ["13.0.0", "12.4.0", "12.3.2", "12.2.2", "12.1.1", "12.0.1", "11.8.0"],
        570: ["12.8.0", "12.4.0", "12.3.2", "12.2.2", "12.1.1", "12.0.1", "11.8.0"],
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


def _install_specific_driver(version: str) -> None:
    """Install specific driver version.

    version can be a full version like '590.48.01' or a major like '590'.
    The apt package name always uses just the major number.
    """
    major = _major_version(version)
    package_name = f"nvidia-driver-{major}"
    log_info(f"Installing NVIDIA driver version {version}...")

    try:
        apt = AptManager()
        apt.install(package_name)
        log_info(f"Successfully installed {package_name}")

        # Clean up stale libraries and fix symlinks from previous driver versions
        _post_install_library_cleanup()

        # Install Vulkan/OpenGL support packages
        _install_vulkan_support(apt, major)

    except subprocess.CalledProcessError:
        log_error(f"Failed to install {package_name}")

        # Try alternative package names
        alternatives = [
            f"nvidia-driver-{major}-server",
            f"nvidia-{major}",
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


def _install_vulkan_support(apt: AptManager, major: str) -> None:
    """Install Vulkan/OpenGL support and verify critical libraries.

    libnvidia-gl-{major} bundles all Vulkan libraries including
    libnvidia-glvkspirv (SPIR-V compiler) and libnvidia-gpucomp
    (GPU compiler).  Without these, Vulkan fails with
    VK_ERROR_INITIALIZATION_FAILED.

    After installing, we verify the libraries exist and regenerate
    the NVIDIA CDI spec so containers can access them.
    """
    # libnvidia-gl bundles: GLX, EGL, Vulkan ICD, glvkspirv, gpucomp
    gl_package = f"libnvidia-gl-{major}"
    log_info(f"Installing Vulkan/OpenGL support: {gl_package}")
    try:
        apt.install(gl_package)
        log_info(f"Successfully installed {gl_package}")
    except Exception:
        log_warn(f"Could not install {gl_package} - Vulkan may not work properly")

    # Verify critical Vulkan libraries are present
    vulkan_libs = [
        ("libnvidia-glvkspirv.so", "Vulkan SPIR-V compiler"),
        ("libnvidia-gpucomp.so", "Vulkan GPU compiler"),
    ]
    lib_dir = "/usr/lib/x86_64-linux-gnu"
    for lib_name, description in vulkan_libs:
        found = any(
            f.startswith(lib_name) for f in os.listdir(lib_dir)
        ) if os.path.isdir(lib_dir) else False
        if found:
            log_info(f"  {description}: found")
        else:
            log_warn(f"  {description}: NOT found — Vulkan may not work")
            log_warn(f"    Expected {lib_name}* in {lib_dir}")

    # Regenerate CDI spec so containers pick up the Vulkan libraries
    _regenerate_cdi_spec()


def _regenerate_cdi_spec() -> None:
    """Regenerate the NVIDIA CDI spec if nvidia-ctk is available.

    This ensures the container toolkit maps all driver libraries
    (including Vulkan) into containers.
    """
    try:
        run_command("nvidia-ctk --version", capture_output=True, check=True)
    except Exception:
        return  # nvidia-ctk not installed, nothing to do

    log_info("Regenerating NVIDIA CDI spec for container Vulkan support...")
    try:
        run_command("nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml")
        log_info("CDI spec regenerated successfully")
    except Exception as exc:
        log_warn(f"Could not regenerate CDI spec: {exc}")
        log_info("Run manually: nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml")


def _post_install_library_cleanup() -> None:
    """Clean up stale NVIDIA libraries after driver installation.

    After installing a new driver, old versioned .so files and broken symlinks
    may remain from previous driver versions.  This removes them and ensures
    all symlinks point to the newly installed driver.
    """
    try:
        # Detect the version that was just installed
        # Try nvidia-smi first, fall back to library filename scanning
        version: str | None = None
        try:
            smi_output = run_command(
                "nvidia-smi --query-gpu=driver_version --format=csv,noheader",
                capture_output=True, check=False,
            )
            if smi_output and re.match(r'^\d+\.\d+', smi_output.strip()):
                version = smi_output.strip()
        except Exception:
            pass

        if version is None:
            version = _detect_driver_version_fallback()

        if version is None:
            log_info("Could not detect installed driver version — skipping library cleanup")
            return

        log_info(f"Cleaning up old libraries for driver {version}...")
        result = cleanup_stale_nvidia_libraries(version, dry_run=False)
        broken = repair_nvidia_symlinks(version, dry_run=False)

        total_cleaned = len(result.get("stale_files", [])) + len(result.get("stale_symlinks", []))
        if total_cleaned or broken:
            log_info(f"Cleaned {total_cleaned} stale file(s) and repaired {len(broken)} symlink(s)")

    except Exception as exc:
        log_warn(f"Library cleanup encountered an error: {exc}")
        log_info("Driver installation was successful — library issues can be fixed manually")


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



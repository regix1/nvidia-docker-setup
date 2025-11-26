"""NVIDIA Vulkan setup and verification"""

import os
from utils.logging import log_info, log_warn, log_error, log_step, log_success
from utils.prompts import prompt_yes_no
from utils.system import run_command, AptManager


def setup_vulkan():
    """Complete Vulkan setup for NVIDIA"""
    log_step("Setting up Vulkan support for NVIDIA...")

    _install_vulkan_packages()
    _verify_vulkan_icd()
    _configure_vulkan_environment()
    _test_vulkan_installation()


def _install_vulkan_packages():
    """Install required Vulkan packages"""
    log_info("Installing Vulkan packages...")

    apt = AptManager()

    # Core Vulkan packages
    vulkan_packages = [
        "libvulkan1",           # Vulkan loader
        "vulkan-tools",         # vulkaninfo and other tools
        "mesa-vulkan-drivers",  # Mesa Vulkan drivers (fallback)
    ]

    apt.install(*vulkan_packages)

    # Install NVIDIA-specific Vulkan packages based on driver version
    driver_version = _get_nvidia_driver_version()
    if driver_version:
        nvidia_gl_package = f"libnvidia-gl-{driver_version}"
        log_info(f"Installing NVIDIA GL package: {nvidia_gl_package}")
        try:
            apt.install(nvidia_gl_package)
        except Exception as e:
            log_warn(f"Could not install {nvidia_gl_package}: {e}")
            log_info("Trying to install latest available libnvidia-gl...")
            try:
                # Try to find any available libnvidia-gl package
                output = run_command(
                    "apt-cache search libnvidia-gl | head -1 | awk '{print $1}'",
                    capture_output=True, check=False
                )
                if output:
                    apt.install(output.strip())
            except:
                log_warn("Could not install libnvidia-gl package")


def _get_nvidia_driver_version():
    """Get installed NVIDIA driver major version"""
    try:
        output = run_command(
            "nvidia-smi --query-gpu=driver_version --format=csv,noheader",
            capture_output=True, check=False
        )
        if output:
            # Extract major version (e.g., "580.95.05" -> "580")
            return output.strip().split('.')[0]
    except:
        pass
    return None


def _verify_vulkan_icd():
    """Verify NVIDIA Vulkan ICD is properly configured"""
    log_info("Verifying Vulkan ICD configuration...")

    icd_paths = [
        "/usr/share/vulkan/icd.d/nvidia_icd.json",
        "/etc/vulkan/icd.d/nvidia_icd.json"
    ]

    icd_found = False
    for path in icd_paths:
        if os.path.exists(path):
            log_info(f"Found Vulkan ICD: {path}")
            icd_found = True

            # Display ICD contents
            try:
                with open(path, 'r') as f:
                    content = f.read()
                    log_info(f"ICD configuration:\n{content}")
            except:
                pass
            break

    if not icd_found:
        log_warn("NVIDIA Vulkan ICD not found!")
        log_info("This may be resolved after driver installation and reboot.")

    # Check for the required library
    lib_path = "/usr/lib/x86_64-linux-gnu/libGLX_nvidia.so.0"
    if os.path.exists(lib_path):
        log_info(f"Found NVIDIA GLX library: {lib_path}")

        # Verify Vulkan symbols exist in the library
        try:
            output = run_command(
                f"nm -D {lib_path} 2>/dev/null | grep -i vk_icd || echo 'No Vulkan symbols'",
                capture_output=True, check=False
            )
            if "vk_icd" in output.lower():
                log_info("Vulkan ICD symbols found in NVIDIA library")
            else:
                log_warn("Vulkan ICD symbols not found - driver may need reinstallation")
        except:
            pass
    else:
        log_warn(f"NVIDIA GLX library not found at {lib_path}")


def _configure_vulkan_environment():
    """Configure Vulkan environment variables"""
    log_info("Configuring Vulkan environment...")

    # Create environment configuration for Vulkan
    vulkan_env_content = """# NVIDIA Vulkan configuration
# Force NVIDIA Vulkan ICD
VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_icd.json

# Optional: Set default Vulkan driver (0 = first GPU, usually NVIDIA)
# VK_DRIVER_FILES=/usr/share/vulkan/icd.d/nvidia_icd.json
"""

    env_file = "/etc/profile.d/nvidia-vulkan.sh"
    try:
        with open(env_file, 'w') as f:
            f.write(vulkan_env_content)
        run_command(f"chmod +x {env_file}")
        log_info(f"Created Vulkan environment config: {env_file}")
    except Exception as e:
        log_warn(f"Could not create Vulkan environment config: {e}")


def _test_vulkan_installation():
    """Test Vulkan installation"""
    log_info("Testing Vulkan installation...")

    try:
        output = run_command("vulkaninfo --summary 2>&1", capture_output=True, check=False)

        if output:
            # Check if NVIDIA GPU is detected
            if "NVIDIA" in output and "GeForce" in output or "RTX" in output or "Quadro" in output:
                log_success("Vulkan detected NVIDIA GPU!")

                # Extract device info
                lines = output.split('\n')
                for line in lines:
                    if 'deviceName' in line and 'NVIDIA' in line:
                        log_info(f"  {line.strip()}")
                    elif 'driverVersion' in line:
                        log_info(f"  {line.strip()}")

            elif "llvmpipe" in output.lower() and "NVIDIA" not in output:
                log_warn("Vulkan only detected software renderer (llvmpipe)")
                log_warn("NVIDIA GPU not detected by Vulkan!")
                _diagnose_vulkan_issues()
            else:
                log_info("Vulkan output:")
                # Print device summary
                in_devices = False
                for line in output.split('\n')[:50]:
                    if 'Devices:' in line:
                        in_devices = True
                    if in_devices:
                        print(f"  {line}")

    except Exception as e:
        log_warn(f"Could not test Vulkan: {e}")
        log_info("vulkan-tools may not be installed yet")


def _diagnose_vulkan_issues():
    """Diagnose common Vulkan issues"""
    log_step("Diagnosing Vulkan issues...")

    issues_found = []

    # Check if NVIDIA driver is loaded
    try:
        output = run_command("lsmod | grep nvidia", capture_output=True, check=False)
        if not output or "nvidia" not in output:
            issues_found.append("NVIDIA kernel module not loaded - reboot required")
    except:
        pass

    # Check if libnvidia-gl is installed
    try:
        output = run_command("dpkg -l | grep libnvidia-gl", capture_output=True, check=False)
        if not output:
            issues_found.append("libnvidia-gl package not installed")
    except:
        pass

    # Check Vulkan loader
    try:
        output = run_command("ldconfig -p | grep vulkan", capture_output=True, check=False)
        if not output or "libvulkan" not in output:
            issues_found.append("Vulkan loader (libvulkan) not found")
    except:
        pass

    # Check for nvidia_icd.json
    if not os.path.exists("/usr/share/vulkan/icd.d/nvidia_icd.json"):
        issues_found.append("NVIDIA Vulkan ICD JSON not found")

    if issues_found:
        log_warn("Potential issues found:")
        for issue in issues_found:
            log_warn(f"  - {issue}")

        log_info("\nSuggested fixes:")
        log_info("  1. Ensure NVIDIA driver is properly installed")
        log_info("  2. Install libnvidia-gl-XXX package (XXX = driver version)")
        log_info("  3. Reboot the system")
        log_info("  4. Run: sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml")
    else:
        log_info("No obvious issues found - try rebooting if Vulkan still doesn't work")


def check_vulkan_status():
    """Check and display Vulkan status"""
    log_step("Checking Vulkan Status")

    status = {
        'vulkan_loader': False,
        'nvidia_icd': False,
        'nvidia_detected': False,
        'working': False
    }

    # Check Vulkan loader
    try:
        output = run_command("ldconfig -p | grep libvulkan", capture_output=True, check=False)
        if output and "libvulkan" in output:
            status['vulkan_loader'] = True
            log_info("Vulkan loader: Installed")
        else:
            log_warn("Vulkan loader: Not found")
    except:
        log_warn("Vulkan loader: Check failed")

    # Check NVIDIA ICD
    if os.path.exists("/usr/share/vulkan/icd.d/nvidia_icd.json"):
        status['nvidia_icd'] = True
        log_info("NVIDIA Vulkan ICD: Found")
    else:
        log_warn("NVIDIA Vulkan ICD: Not found")

    # Check if NVIDIA is detected by Vulkan
    try:
        output = run_command("vulkaninfo --summary 2>&1 | grep -i nvidia", capture_output=True, check=False)
        if output and "nvidia" in output.lower():
            status['nvidia_detected'] = True
            status['working'] = True
            log_success("NVIDIA GPU detected by Vulkan")
        else:
            log_warn("NVIDIA GPU not detected by Vulkan")
    except:
        log_warn("Could not check Vulkan GPU detection")

    return status


def configure_docker_vulkan():
    """Configure Docker for Vulkan support"""
    log_step("Configuring Docker for Vulkan support...")

    # Generate CDI spec for GPU access
    log_info("Generating NVIDIA CDI specification...")
    try:
        run_command("nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml")
        log_info("CDI specification generated")
    except Exception as e:
        log_warn(f"Could not generate CDI spec: {e}")

    # Ensure nvidia-container-toolkit is up to date
    log_info("Checking nvidia-container-toolkit version...")
    try:
        output = run_command("nvidia-ctk --version", capture_output=True, check=False)
        if output:
            log_info(f"nvidia-container-toolkit: {output.strip()}")

            # Check if version is recent enough (1.14+)
            version_line = output.strip()
            if "version" in version_line.lower():
                version_num = version_line.split()[-1]
                major_minor = version_num.split('.')[:2]
                if len(major_minor) >= 2:
                    major = int(major_minor[0])
                    minor = int(major_minor[1])
                    if major < 1 or (major == 1 and minor < 14):
                        log_warn("nvidia-container-toolkit version < 1.14 may have Vulkan issues")
                        log_info("Consider upgrading: apt update && apt install nvidia-container-toolkit")
    except Exception as e:
        log_warn(f"Could not check toolkit version: {e}")

    log_info("\nDocker Compose Vulkan configuration example:")
    print("""
    services:
      your-service:
        runtime: nvidia
        environment:
          - NVIDIA_DRIVER_CAPABILITIES=all  # Include 'graphics' for Vulkan
          - NVIDIA_VISIBLE_DEVICES=all
          - VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_icd.json
    """)


def show_vulkan_info():
    """Display comprehensive Vulkan information"""
    info = """
                    NVIDIA Vulkan Information

What is Vulkan?
  Vulkan is a low-level graphics and compute API that provides high-efficiency,
  cross-platform access to GPUs. For NVIDIA GPUs, it enables GPU-accelerated
  applications like video upscaling (NCNN), gaming, and compute workloads.

Key Components:
  - Vulkan Loader (libvulkan.so): Routes Vulkan calls to the GPU driver
  - NVIDIA ICD (Installable Client Driver): NVIDIA's Vulkan implementation
  - nvidia_icd.json: Configuration file pointing to NVIDIA's Vulkan driver

Required Packages:
  - libvulkan1: Vulkan loader library
  - vulkan-tools: Diagnostic tools (vulkaninfo)
  - libnvidia-gl-XXX: NVIDIA OpenGL/Vulkan libraries (XXX = driver version)

Docker Container Setup:
  For Vulkan to work in Docker containers, you need:
  1. nvidia-container-toolkit 1.14+ (with graphics capability support)
  2. NVIDIA_DRIVER_CAPABILITIES=all or NVIDIA_DRIVER_CAPABILITIES=graphics
  3. Container must have libvulkan1 installed

Common Issues:
  - "llvmpipe" detected instead of NVIDIA: Missing libnvidia-gl package
  - "vkCreateInstance failed": Vulkan ICD not properly configured
  - Container can't access GPU: Missing NVIDIA runtime or capabilities

Verification Commands:
  - Host: vulkaninfo --summary
  - Docker: docker run --rm --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all \\
            nvidia/cuda:12.0-base vulkaninfo --summary

Troubleshooting:
  1. Verify driver is loaded: nvidia-smi
  2. Check Vulkan ICD: cat /usr/share/vulkan/icd.d/nvidia_icd.json
  3. Verify library: ls -la /usr/lib/x86_64-linux-gnu/libGLX_nvidia.so*
  4. Regenerate CDI: nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
  5. Restart Docker: systemctl restart docker
"""
    print(info)

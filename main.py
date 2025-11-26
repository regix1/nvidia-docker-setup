#!/usr/bin/env python3
"""
NVIDIA Docker Setup - Python Version
Installs/updates NVIDIA drivers and Docker with NVIDIA support, optimized for Plex and FFmpeg
Written for Ubuntu 22.04 (Jammy)
"""

import os
import sys
import traceback

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.logging import log_error, log_step, log_info, log_success
from utils.prompts import prompt_yes_no, prompt_choice
from system.checks import run_preliminary_checks, detect_existing_installations, get_system_info, display_system_info
from nvidia.drivers import select_nvidia_driver
from nvidia.cuda import select_cuda_version
from nvidia.vulkan import setup_vulkan, check_vulkan_status, show_vulkan_info
from docker.setup import setup_docker
from nvidia.patches import apply_nvidia_patches
from docker.config import configure_docker_for_media
from system.checks import check_gpu_capabilities


def show_banner():
    """Display application banner"""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                NVIDIA Docker Setup - Python                  ║
║          Hardware Acceleration for Media Servers            ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(banner)


def show_main_menu(installations, system_info=None):
    """Show main installation menu based on detected installations"""
    log_step("Installation Options")

    options = []
    descriptions = []

    # NVIDIA Drivers
    if installations['nvidia_driver']['installed']:
        nvidia_text = f"Reinstall NVIDIA Drivers (Current: {installations['nvidia_driver']['version']})"
        nvidia_desc = "Reinstall or update NVIDIA drivers"
    else:
        nvidia_text = "Install NVIDIA Drivers"
        nvidia_desc = "Install NVIDIA GPU drivers"
    options.append(nvidia_text)
    descriptions.append(nvidia_desc)

    # Docker
    if installations['docker']['installed']:
        docker_text = f"Reconfigure Docker (Current: {installations['docker']['version']})"
        docker_desc = "Reconfigure Docker with NVIDIA support"
    else:
        docker_text = "Install Docker with NVIDIA Support"
        docker_desc = "Install Docker and NVIDIA Container Toolkit"
    options.append(docker_text)
    descriptions.append(docker_desc)

    # CUDA
    cuda_text = "Select CUDA Version"
    cuda_desc = "Choose CUDA version for containers"
    options.append(cuda_text)
    descriptions.append(cuda_desc)

    # Vulkan - show hardware support status
    vulkan_hw_supported = system_info and system_info.get('capabilities', {}).get('vulkan_supported', True)
    if installations['vulkan']['installed']:
        vulkan_status = installations['vulkan']['version']
        vulkan_text = f"Configure Vulkan (Current: {vulkan_status})"
        vulkan_desc = "Reconfigure Vulkan support for GPU compute"
    else:
        vulkan_text = "Setup Vulkan Support"
        if vulkan_hw_supported:
            vulkan_desc = "Install Vulkan for GPU compute (NCNN, etc.)"
        else:
            vulkan_desc = "Install Vulkan [!] Hardware may not support GPU Vulkan"
    options.append(vulkan_text)
    descriptions.append(vulkan_desc)

    # Patches
    patch_text = "Apply NVIDIA Patches (NVENC/NvFBC)"
    patch_desc = "Remove NVENC session limits and enable NvFBC"
    options.append(patch_text)
    descriptions.append(patch_desc)

    # Media Config
    media_text = "Configure for Media Servers"
    media_desc = "Optimize Docker for Plex/media processing"
    options.append(media_text)
    descriptions.append(media_desc)

    # Full installation
    full_text = "Complete Installation (All Components)"
    full_desc = "Install/configure everything automatically"
    options.append(full_text)
    descriptions.append(full_desc)

    # Exit
    options.append("Exit")
    descriptions.append("Exit without changes")

    # Display menu
    print("\nSelect installation options:")
    for i, (option, desc) in enumerate(zip(options, descriptions), 1):
        status = ""
        if i == 1 and installations['nvidia_driver']['installed']:
            status = " [OK]"
        elif i == 2 and installations['docker']['installed']:
            status = " [OK]"
        elif i == 4 and installations['vulkan']['installed']:
            status = " [OK]" if "NVIDIA" in str(installations['vulkan']['version']) else " [!]"

        print(f"  {i}. {option}{status}")
        print(f"     {desc}")
        print()

    return options


def handle_menu_selection(choice, installations):
    """Handle the selected menu option"""
    if choice == 0:  # NVIDIA Drivers
        if installations['nvidia_driver']['installed']:
            if prompt_yes_no(f"NVIDIA driver {installations['nvidia_driver']['version']} is installed. Reinstall?"):
                select_nvidia_driver()
        else:
            select_nvidia_driver()

    elif choice == 1:  # Docker
        if installations['docker']['installed']:
            if prompt_yes_no(f"Docker {installations['docker']['version']} is installed. Reconfigure?"):
                setup_docker()
        else:
            setup_docker()

    elif choice == 2:  # CUDA
        select_cuda_version()

    elif choice == 3:  # Vulkan
        if installations['vulkan']['installed'] and "NVIDIA" in str(installations['vulkan']['version']):
            # Vulkan already working, offer info or reconfigure
            print("\nVulkan Options:")
            print("  1. Show Vulkan information")
            print("  2. Check Vulkan status")
            print("  3. Reconfigure Vulkan")
            vulkan_choice = prompt_choice("Select option", ["Info", "Status", "Reconfigure"], default=1)
            if vulkan_choice == 0:
                show_vulkan_info()
            elif vulkan_choice == 1:
                check_vulkan_status()
            else:
                setup_vulkan()
        else:
            setup_vulkan()

    elif choice == 4:  # Patches
        apply_nvidia_patches()

    elif choice == 5:  # Media Config
        configure_docker_for_media()

    elif choice == 6:  # Complete Installation
        run_complete_installation(installations)

    elif choice == 7:  # Exit
        log_info("Exiting without changes.")
        sys.exit(0)


def run_complete_installation(installations):
    """Run complete installation process"""
    log_step("Running Complete Installation")

    # Install/reinstall NVIDIA drivers if needed
    if not installations['nvidia_driver']['installed'] or prompt_yes_no("Reinstall NVIDIA drivers?"):
        select_nvidia_driver()

    # Select CUDA version
    cuda_version = select_cuda_version()

    # Setup Vulkan support
    if not installations['vulkan']['installed'] or "NVIDIA" not in str(installations['vulkan'].get('version', '')):
        log_step("Setting up Vulkan support...")
        setup_vulkan()

    # Install/reconfigure Docker
    if not installations['docker']['installed'] or prompt_yes_no("Reconfigure Docker?"):
        setup_docker()

    # Apply patches
    apply_nvidia_patches()

    # Configure for media
    configure_docker_for_media()

    # Check capabilities
    check_gpu_capabilities()

    # Final Vulkan check
    log_step("Final Vulkan verification...")
    check_vulkan_status()


def show_post_installation_summary():
    """Show post-installation summary and next steps"""
    log_success("Installation completed successfully!")

    summary = """
======================================================================
                       Installation Summary
======================================================================

Next Steps:
1. Reboot your system for all changes to take effect

2. Test NVIDIA Docker integration:
   docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi

3. Test Vulkan support (after reboot):
   # On host:
   vulkaninfo --summary

   # In container:
   docker run --rm --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all \\
     nvidia/cuda:12.0-base bash -c "apt update && apt install -y vulkan-tools && vulkaninfo --summary"

4. For Plex with GPU acceleration:
   - Copy template: cp templates/plex-nvidia.yml /opt/docker-templates/
   - Edit paths and claim token
   - Start: docker-compose -f /opt/docker-templates/plex-nvidia.yml up -d

5. For containers requiring Vulkan (NCNN, etc.):
   Add to docker-compose.yml:
     environment:
       - NVIDIA_DRIVER_CAPABILITIES=all
       - VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_icd.json

6. Performance optimization (recommended):
   - Add kernel parameters: pcie_port_pm=off pcie_aspm.policy=performance
   - Edit /etc/default/grub and run update-grub

Troubleshooting Vulkan in containers:
   - Ensure libnvidia-gl-XXX is installed (XXX = driver version)
   - Update nvidia-container-toolkit: apt install nvidia-container-toolkit
   - Regenerate CDI: nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
   - Restart Docker: systemctl restart docker
======================================================================
"""

    print(summary)


def main():
    """Main installation process"""
    try:
        # Check if running as root
        if os.geteuid() != 0:
            log_error("This script must be run as root (sudo).")
            sys.exit(1)

        show_banner()

        # Gather and display system information first
        log_step("Gathering System Information")
        system_info = get_system_info()
        display_system_info(system_info)

        # Run system checks
        run_preliminary_checks()

        # Detect existing installations
        log_step("Detecting Installed Components")
        installations = detect_existing_installations()

        # Show installation status
        print("\nInstallation Status:")
        print(f"  NVIDIA Driver:  {'[OK] ' + installations['nvidia_driver']['version'] if installations['nvidia_driver']['installed'] else '[--] Not installed'}")
        print(f"  Docker:         {'[OK] ' + installations['docker']['version'] if installations['docker']['installed'] else '[--] Not installed'}")
        print(f"  NVIDIA Runtime: {'[OK] Available' if installations['nvidia_runtime']['installed'] else '[--] Not configured'}")

        # Vulkan installation status (separate from hardware support)
        if installations['vulkan']['installed']:
            vulkan_ver = installations['vulkan']['version']
            if "NVIDIA" in str(vulkan_ver):
                print(f"  Vulkan Tools:   [OK] {vulkan_ver}")
            else:
                print(f"  Vulkan Tools:   [!!] {vulkan_ver} (NVIDIA GPU not detected)")
        else:
            print(f"  Vulkan Tools:   [--] Not installed")

        # Show recommendation if Vulkan not supported
        if not system_info['capabilities']['vulkan_supported']:
            print("\n  [!] Your GPU does not support Vulkan compute.")
            print("      For AI/upscaling workloads, use PyTorch/CUDA backend instead of NCNN.")
        print()
        
        # Interactive menu loop
        while True:
            options = show_main_menu(installations, system_info)

            choice = prompt_choice(
                "What would you like to do?",
                options,
                default=5 if not any(inst['installed'] for inst in installations.values()) else None
            )
            
            if choice == len(options) - 1:  # Exit option
                log_info("Exiting without changes.")
                break
            
            handle_menu_selection(choice, installations)
            
            # Refresh installation status
            installations = detect_existing_installations()
            
            if not prompt_yes_no("Would you like to perform additional actions?"):
                break
        
        show_post_installation_summary()
        
        if prompt_yes_no("Would you like to reboot now?"):
            os.system("reboot")
            
    except KeyboardInterrupt:
        log_error("Installation cancelled by user")
        sys.exit(1)
    except Exception as e:
        log_error(f"Installation failed: {str(e)}")
        log_error(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
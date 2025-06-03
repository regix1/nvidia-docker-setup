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

from utils.logging import log_error, log_step
from utils.prompts import prompt_yes_no
from system.checks import run_preliminary_checks
from nvidia.drivers import select_nvidia_driver
from nvidia.cuda import select_cuda_version
from docker.setup import setup_docker
from nvidia.patches import apply_nvidia_patches
from docker.config import configure_docker_for_media
from system.checks import check_gpu_capabilities


def main():
    """Main installation process"""
    try:
        # Check if running as root
        if os.geteuid() != 0:
            log_error("This script must be run as root (sudo).")
            sys.exit(1)

        log_step("Starting NVIDIA Docker Setup")
        
        # Run system checks
        run_preliminary_checks()
        
        # Install NVIDIA drivers
        if prompt_yes_no("Install/update NVIDIA drivers?"):
            select_nvidia_driver()
        
        # Select CUDA version
        cuda_version = select_cuda_version()
        
        # Setup Docker
        if prompt_yes_no("Install/setup Docker with NVIDIA support?"):
            setup_docker()
        
        # Apply NVIDIA patches
        apply_nvidia_patches()
        
        # Configure Docker for media
        configure_docker_for_media()
        
        # Check GPU capabilities
        check_gpu_capabilities()
        
        log_step("Installation completed successfully!")
        print("\n" + "="*60)
        print("IMPORTANT: You may need to reboot for all changes to take effect.")
        print("After reboot, test with: docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi")
        print("="*60)
        
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
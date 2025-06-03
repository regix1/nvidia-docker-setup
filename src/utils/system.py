"""System utilities for command execution and package management"""

import subprocess
import os
from .logging import log_info, log_error, log_warn


def run_command(cmd, shell=True, check=True, capture_output=False):
    """
    Execute a system command with logging
    
    Args:
        cmd: Command to execute (string or list)
        shell: Whether to use shell
        check: Whether to raise exception on failure
        capture_output: Whether to capture and return output
    
    Returns:
        CompletedProcess object or output string if capture_output=True
    """
    log_info(f"Running: {cmd}")
    
    try:
        if capture_output:
            result = subprocess.run(cmd, shell=shell, check=check, 
                                  capture_output=True, text=True)
            return result.stdout.strip()
        else:
            result = subprocess.run(cmd, shell=shell, check=check)
            return result
    except subprocess.CalledProcessError as e:
        log_error(f"Command failed: {cmd}")
        if check:
            raise
        return None


class AptManager:
    """Manages apt operations with caching"""
    
    def __init__(self):
        self._update_cache = False
    
    def update(self):
        """Update apt cache if not already done"""
        if not self._update_cache:
            run_command("apt-get update")
            self._update_cache = True
    
    def install(self, *packages):
        """Install packages using apt"""
        self.update()
        package_list = ' '.join(packages)
        env = os.environ.copy()
        env['DEBIAN_FRONTEND'] = 'noninteractive'
        
        cmd = f"apt-get install -y {package_list}"
        subprocess.run(cmd, shell=True, check=True, env=env)
    
    def remove(self, *packages, purge=False):
        """Remove packages"""
        package_list = ' '.join(packages)
        flag = "--purge" if purge else ""
        run_command(f"apt-get remove {flag} -y {package_list}")
    
    def autoremove(self, purge=False):
        """Remove unnecessary packages"""
        flag = "--purge" if purge else ""
        run_command(f"apt-get autoremove {flag} -y")


def cleanup_nvidia_repos():
    """Clean up existing NVIDIA repository files and fix driver mismatches"""
    log_info("Cleaning up NVIDIA repository files...")
    
    # Repository files to remove
    repo_files = [
        "/etc/apt/sources.list.d/nvidia-docker.list",
        "/etc/apt/sources.list.d/nvidia-container-toolkit.list",
        "/etc/apt/sources.list.d/nvidia*.list"
    ]
    
    # Keyring files to remove
    keyring_files = [
        "/etc/apt/keyrings/nvidia-docker.gpg",
        "/etc/apt/keyrings/nvidia-*.gpg",
        "/usr/share/keyrings/nvidia-docker.gpg",
        "/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg"
    ]
    
    # Remove files
    for pattern in repo_files + keyring_files:
        run_command(f"rm -f {pattern}", check=False)
    
    # Check for driver version mismatch
    try:
        nvidia_smi_output = run_command("nvidia-smi", capture_output=True, check=False)
        if nvidia_smi_output and "Driver/library version mismatch" in nvidia_smi_output:
            log_warn("Detected NVIDIA driver version mismatch. Cleaning up...")
            apt = AptManager()
            apt.remove("'^nvidia-.*'", purge=True)
            apt.autoremove(purge=True)
            run_command("update-initramfs -u")
    except:
        pass  # nvidia-smi not available or failed


def check_internet():
    """Check internet connectivity"""
    try:
        run_command("ping -c 1 8.8.8.8", capture_output=True)
        return True
    except:
        return False


def get_os_info():
    """Get OS information from /etc/os-release"""
    try:
        with open('/etc/os-release', 'r') as f:
            lines = f.readlines()
        
        info = {}
        for line in lines:
            if '=' in line:
                key, value = line.strip().split('=', 1)
                info[key] = value.strip('"')
        
        return info
    except:
        return {}


def check_nvidia_gpu():
    """Check if NVIDIA GPU is present"""
    try:
        output = run_command("lspci | grep -i nvidia", capture_output=True, check=False)
        return bool(output)
    except:
        return False
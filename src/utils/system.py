"""System utilities for command execution and package management"""

import re
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
                                  capture_output=True, text=True,
                                  stdin=subprocess.DEVNULL)
            return result.stdout.strip()
        else:
            result = subprocess.run(cmd, shell=shell, check=check,
                                  stdin=subprocess.DEVNULL)
            return result
    except subprocess.CalledProcessError as e:
        log_error(f"Command failed: {cmd}")
        if check:
            raise
        return None


class AptManager:
    """Manages apt operations with caching"""

    _update_done: bool = False

    def update(self):
        """Update apt cache if not already done"""
        if not AptManager._update_done:
            run_command("apt-get update")
            AptManager._update_done = True

    @classmethod
    def reset_cache(cls):
        """Reset the update cache so the next update() call re-runs apt-get update.

        Call this after adding new repositories so packages from
        those repos can be discovered.
        """
        cls._update_done = False

    def install(self, *packages):
        """Install packages using apt"""
        self.update()
        package_list = ' '.join(packages)
        env = os.environ.copy()
        env['DEBIAN_FRONTEND'] = 'noninteractive'

        cmd = f"apt-get install -y {package_list}"
        log_info(f"Running: {cmd}")
        subprocess.run(cmd, shell=True, check=True, env=env)

    def remove(self, *packages, purge: bool = False, check: bool = True):
        """Remove packages

        Args:
            packages: Package names to remove
            purge: Whether to purge configuration files
            check: Whether to raise on failure (default True)
        """
        package_list = ' '.join(packages)
        flag = "--purge" if purge else ""
        run_command(f"apt-get remove {flag} -y {package_list}", check=check)

    def autoremove(self, purge: bool = False):
        """Remove unnecessary packages"""
        flag = "--purge" if purge else ""
        run_command(f"apt-get autoremove {flag} -y")


def cleanup_nvidia_repos():
    """Clean up stale NVIDIA repository and keyring files.

    Only removes repo/keyring files that may conflict with fresh setup.
    Does NOT touch installed driver packages - use cleanup_old_nvidia_drivers() for that.
    """
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

    for pattern in repo_files + keyring_files:
        run_command(f"rm -f {pattern}", check=False)


def cleanup_old_nvidia_drivers() -> bool:
    """Detect and remove old NVIDIA driver packages, keeping only the newest.

    Queries dpkg for all installed nvidia-driver-XXX packages, identifies
    the highest version, and offers to purge all others.  This removes
    stale libraries (e.g. libnvidia-encode.so.565.*) that confuse version
    detection after driver upgrades.

    Returns:
        True if packages were removed, False otherwise.
    """
    try:
        result = subprocess.run(
            "dpkg -l 'nvidia-driver-*' 2>/dev/null",
            shell=True, capture_output=True, text=True,
        )
        if result.returncode != 0:
            return False

        # Parse installed nvidia-driver-XXX packages
        installed: list[tuple[int, str]] = []  # (major, full_package_name)
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "ii":
                match = re.match(r'^(nvidia-driver-(\d+))$', parts[1])
                if match:
                    installed.append((int(match.group(2)), match.group(1)))

        if len(installed) <= 1:
            return False

        installed.sort(key=lambda entry: entry[0])
        newest_major, newest_pkg = installed[-1]
        old_packages = [pkg for _major, pkg in installed[:-1]]

        log_warn(f"Multiple NVIDIA driver versions installed:")
        for major, pkg in installed:
            marker = " (newest)" if pkg == newest_pkg else " (old)"
            log_info(f"  {pkg}{marker}")

        log_info(f"Old driver packages leave stale libraries on disk that can cause issues.")
        log_info(f"Keeping: {newest_pkg}")
        log_info(f"Will remove: {', '.join(old_packages)}")

        apt = AptManager()
        apt.remove(*old_packages, purge=True, check=False)
        apt.autoremove(purge=True)
        log_info("✓ Old NVIDIA driver packages removed")
        return True

    except Exception as e:
        log_warn(f"Could not check for old driver packages: {e}")
        return False


def check_internet():
    """Check internet connectivity"""
    try:
        run_command("ping -c 1 8.8.8.8", capture_output=True)
        return True
    except Exception:
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
    except Exception:
        return {}


def check_nvidia_gpu():
    """Check if NVIDIA GPU is present"""
    try:
        output = run_command("lspci | grep -i nvidia", capture_output=True, check=False)
        return bool(output)
    except Exception:
        return False
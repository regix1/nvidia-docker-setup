"""System utilities for command execution and package management"""

import re
import subprocess
import os
from datetime import datetime
from .logging import log_info, log_error, log_warn, log_step, log_success


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

    Queries dpkg for all installed nvidia-driver-XXX packages (including
    -server variants and associated library packages), identifies the highest
    version, and offers to purge all others.

    Returns:
        True if packages were removed, False otherwise.
    """
    try:
        result = subprocess.run(
            "dpkg -l 'nvidia-*' 2>/dev/null",
            shell=True, capture_output=True, text=True,
        )
        if result.returncode != 0:
            return False

        # Collect all installed nvidia packages with a version number in the name
        # e.g. nvidia-driver-590, nvidia-driver-565-server, libnvidia-encode-580
        versioned_re = re.compile(
            r'^((?:nvidia-driver|libnvidia-\w+|nvidia-utils|nvidia-compute-utils'
            r'|nvidia-kernel-common|nvidia-kernel-source|nvidia-dkms'
            r'|xserver-xorg-video-nvidia)-(\d+)(?:-server)?)$'
        )

        # Map major version -> list of package names
        packages_by_major: dict[int, list[str]] = {}
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] in ("ii", "hi"):
                match = versioned_re.match(parts[1])
                if match:
                    pkg_name = match.group(1)
                    major = int(match.group(2))
                    packages_by_major.setdefault(major, []).append(pkg_name)

        if len(packages_by_major) <= 1:
            return False

        newest_major = max(packages_by_major)
        old_majors = sorted(m for m in packages_by_major if m != newest_major)

        log_warn("Multiple NVIDIA driver versions installed:")
        for major in sorted(packages_by_major):
            marker = " (newest - keeping)" if major == newest_major else " (old - will remove)"
            pkg_list = ", ".join(packages_by_major[major])
            log_info(f"  {major}: {pkg_list}{marker}")

        old_packages: list[str] = []
        for major in old_majors:
            old_packages.extend(packages_by_major[major])

        log_info(f"Will remove {len(old_packages)} old package(s)")

        apt = AptManager()
        apt.remove(*old_packages, purge=True, check=False)
        apt.autoremove(purge=True)
        log_info("Old NVIDIA driver packages removed")
        return True

    except Exception as e:
        log_warn(f"Could not check for old driver packages: {e}")
        return False


def get_running_driver_version() -> str | None:
    """Get the currently running NVIDIA driver version from nvidia-smi.

    Returns:
        Full version string (e.g. '590.48.01') or None if not available.
    """
    try:
        output = subprocess.run(
            "nvidia-smi --query-gpu=driver_version --format=csv,noheader",
            shell=True, capture_output=True, text=True,
        )
        if output.returncode == 0:
            version = output.stdout.strip()
            if re.match(r'^\d+\.\d+', version):
                return version
    except OSError:
        pass
    return None


def _get_installed_nvidia_packages() -> list[tuple[str, str]]:
    """Query dpkg for all installed NVIDIA packages.

    Returns:
        List of (package_name, version_string) tuples for installed NVIDIA packages.
    """
    try:
        result = subprocess.run(
            "dpkg -l | grep -i nvidia",
            shell=True, capture_output=True, text=True,
        )
        if result.returncode != 0:
            return []

        packages: list[tuple[str, str]] = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0] in ("ii", "hi"):
                packages.append((parts[1], parts[2]))
        return packages
    except OSError:
        return []


def audit_nvidia_packages(current_major: str | None = None) -> dict[str, list[tuple[str, str]]]:
    """Audit all installed NVIDIA packages and categorize them.

    Dynamically detects the current driver major version and categorizes all
    installed NVIDIA packages as CURRENT, OLD, or OTHER.  No versions are
    hardcoded -- the running driver is detected via nvidia-smi.

    Args:
        current_major: Override for the current driver major version.
            If None, auto-detected from nvidia-smi.

    Returns:
        Dict with keys 'current', 'old', 'other', each mapping to a list
        of (package_name, version_string) tuples.
    """
    log_step("Auditing installed NVIDIA packages...")

    if current_major is None:
        version = get_running_driver_version()
        if version:
            current_major = version.split(".")[0]

    packages = _get_installed_nvidia_packages()
    if not packages:
        log_warn("No NVIDIA packages found")
        return {"current": [], "old": [], "other": []}

    categorized: dict[str, list[tuple[str, str]]] = {
        "current": [], "old": [], "other": [],
    }

    for pkg_name, pkg_version in packages:
        if current_major is None:
            # Cannot categorize without knowing the current version
            categorized["other"].append((pkg_name, pkg_version))
            log_info(f"  [OTHER] {pkg_name} ({pkg_version})")
            continue

        # Check if the package or its version contains the current major version
        is_current = (
            current_major in pkg_version
            or f"-{current_major}" in pkg_name
        )
        if is_current:
            categorized["current"].append((pkg_name, pkg_version))
            log_success(f"  [CURRENT] {pkg_name} ({pkg_version})")
            continue

        # Check if the package NAME contains a driver major version number
        # Only packages with a version suffix in the name (e.g. nvidia-driver-565,
        # libnvidia-encode-580) are driver-versioned.  Packages like nvidia-settings,
        # nvidia-prime, nvtop are standalone utilities whose package version (e.g.
        # 510.47.03) does NOT indicate a driver version.
        pkg_major_match = re.search(r'-(\d{3,})', pkg_name)
        detected_major: str | None = None
        if pkg_major_match:
            detected_major = pkg_major_match.group(1)

        if detected_major and detected_major != current_major:
            categorized["old"].append((pkg_name, pkg_version))
            log_warn(f"  [OLD] {pkg_name} ({pkg_version})")
        else:
            categorized["other"].append((pkg_name, pkg_version))
            log_info(f"  [OTHER] {pkg_name} ({pkg_version})")

    if categorized["old"]:
        log_warn(f"Found {len(categorized['old'])} package(s) from old driver versions")
    else:
        log_success("No old driver packages found")

    log_info(f"Found {len(categorized['current'])} package(s) for current driver "
             f"{current_major or '(unknown)'}")
    return categorized


def audit_nvidia_repos() -> dict[str, list[str]]:
    """Audit NVIDIA-related APT repository sources.

    Checks /etc/apt/sources.list and /etc/apt/sources.list.d/ for any
    NVIDIA repository entries.  Also queries apt-cache policy for the
    current driver package.

    Returns:
        Dict with keys:
            'sources_list_entries': lines from sources.list mentioning nvidia
            'sources_list_d_files': files in sources.list.d referencing nvidia
    """
    log_step("Checking NVIDIA package sources...")

    result: dict[str, list[str]] = {
        "sources_list_entries": [],
        "sources_list_d_files": [],
    }

    # Check /etc/apt/sources.list
    sources_list = "/etc/apt/sources.list"
    if os.path.isfile(sources_list):
        try:
            with open(sources_list, "r") as fh:
                for line in fh:
                    if "nvidia" in line.lower():
                        result["sources_list_entries"].append(line.strip())
        except OSError:
            pass

    if result["sources_list_entries"]:
        log_info("Found NVIDIA entries in /etc/apt/sources.list:")
        for entry in result["sources_list_entries"]:
            log_info(f"    {entry}")

    # Check /etc/apt/sources.list.d/
    sources_dir = "/etc/apt/sources.list.d"
    if os.path.isdir(sources_dir):
        try:
            for entry in os.scandir(sources_dir):
                if not entry.is_file():
                    continue
                if not entry.name.endswith((".list", ".sources")):
                    continue
                try:
                    with open(entry.path, "r") as fh:
                        content = fh.read()
                    if "nvidia" in content.lower():
                        result["sources_list_d_files"].append(entry.path)
                except OSError:
                    continue
        except OSError:
            pass

    if result["sources_list_d_files"]:
        log_info("Found NVIDIA repositories in sources.list.d:")
        for filepath in result["sources_list_d_files"]:
            log_info(f"    {filepath}")

    if not result["sources_list_entries"] and not result["sources_list_d_files"]:
        log_info("No NVIDIA repository entries found in APT sources")

    # Check apt-cache policy for current driver
    current_version = get_running_driver_version()
    if current_version:
        major = current_version.split(".")[0]
        policy_output = run_command(
            f"apt-cache policy nvidia-driver-{major} 2>/dev/null",
            capture_output=True, check=False,
        )
        if policy_output:
            log_info(f"Repository policy for nvidia-driver-{major}:")
            for line in policy_output.splitlines():
                log_info(f"  {line}")

    return result


def create_apt_pin_file(major_version: str, dry_run: bool = True) -> bool:
    """Create an APT preferences pin file to prevent NVIDIA driver upgrades.

    Creates /etc/apt/preferences.d/nvidia-pin with Pin-Priority 1001 so that
    only the current major version can be installed, blocking accidental
    upgrades to a newer major version.

    Args:
        major_version: The driver major version to pin (e.g. '590').
        dry_run: If True, only report what would be created.

    Returns:
        True if the pin file was created (or would be in dry-run).
    """
    pin_path = "/etc/apt/preferences.d/nvidia-pin"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    pin_content = (
        f"# Pin NVIDIA driver version {major_version}\n"
        f"# Generated by nvidia-driver-setup on {timestamp}\n"
        f"\n"
        f"Package: nvidia-driver-{major_version}\n"
        f"Pin: version {major_version}.*\n"
        f"Pin-Priority: 1001\n"
        f"\n"
        f"Package: nvidia-*-{major_version}\n"
        f"Pin: version {major_version}.*\n"
        f"Pin-Priority: 1001\n"
    )

    if dry_run:
        log_info(f"[DRY-RUN] Would create {pin_path} with content:")
        for line in pin_content.splitlines():
            log_info(f"    {line}")
        return True

    try:
        with open(pin_path, "w") as fh:
            fh.write(pin_content)
        log_success(f"Created APT pin file: {pin_path}")
        return True
    except OSError as exc:
        log_error(f"Failed to create {pin_path}: {exc}")
        return False


def manage_unattended_upgrades_blacklist(dry_run: bool = True) -> bool:
    """Add NVIDIA packages to the unattended-upgrades blacklist.

    Checks /etc/apt/apt.conf.d/50unattended-upgrades for existing NVIDIA
    entries and adds them if missing.  Creates a timestamped backup before
    modifying the file.

    Args:
        dry_run: If True, only report what would be done.

    Returns:
        True if NVIDIA is already blacklisted or was successfully added.
    """
    config_path = "/etc/apt/apt.conf.d/50unattended-upgrades"

    if not os.path.isfile(config_path):
        log_info("unattended-upgrades not configured (file not found)")
        return False

    try:
        with open(config_path, "r") as fh:
            content = fh.read()
    except OSError as exc:
        log_warn(f"Cannot read {config_path}: {exc}")
        return False

    # Check if NVIDIA is already blacklisted
    if "nvidia" in content.lower():
        log_success("NVIDIA already in unattended-upgrades blacklist")
        # Show context around the nvidia entry
        for line in content.splitlines():
            if "nvidia" in line.lower():
                log_info(f"    {line.strip()}")
        return True

    if dry_run:
        log_info("[DRY-RUN] Would add NVIDIA to Package-Blacklist "
                 f"in {config_path}")
        log_info('[DRY-RUN] Would add: "nvidia-*";')
        return True

    # Check if Package-Blacklist section exists
    blacklist_pattern = r'Unattended-Upgrade::Package-Blacklist\s*\{'
    has_blacklist_section = bool(re.search(blacklist_pattern, content))

    if has_blacklist_section:
        # Create backup before modifying
        backup_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{config_path}.backup.{backup_suffix}"
        try:
            with open(backup_path, "w") as fh:
                fh.write(content)
            log_info(f"Created backup: {backup_path}")
        except OSError as exc:
            log_warn(f"Could not create backup: {exc}")
            return False

        # Insert nvidia-* into the blacklist section
        modified = re.sub(
            blacklist_pattern,
            'Unattended-Upgrade::Package-Blacklist {\n    "nvidia-*";',
            content,
            count=1,
        )

        try:
            with open(config_path, "w") as fh:
                fh.write(modified)
            log_success("Added NVIDIA to unattended-upgrades blacklist")
            log_warn("Please verify the configuration manually:")
            log_info(f"    nano {config_path}")
            return True
        except OSError as exc:
            log_error(f"Failed to modify {config_path}: {exc}")
            return False
    else:
        log_warn("Could not find Package-Blacklist section in unattended-upgrades config")
        log_info(f"Please manually add to {config_path}:")
        log_info('    Unattended-Upgrade::Package-Blacklist {')
        log_info('        "nvidia-*";')
        log_info('    };')
        return False


def verify_nvidia_cleanup_state(dry_run: bool = True) -> dict[str, bool]:
    """Verify the final state of NVIDIA driver cleanup and pinning.

    Shows installed packages, held packages, APT pin file status,
    and unattended-upgrades blacklist status.

    Args:
        dry_run: Whether we are in dry-run mode (affects messaging).

    Returns:
        Dict with verification results:
            'packages_ok': True if only current driver packages are installed
            'holds_ok': True if packages are held
            'pin_file_ok': True if APT pin file exists
            'unattended_ok': True if NVIDIA is in unattended-upgrades blacklist
    """
    log_step("Verifying NVIDIA cleanup state...")
    results: dict[str, bool] = {
        "packages_ok": False,
        "holds_ok": False,
        "pin_file_ok": False,
        "unattended_ok": False,
    }

    # 1. Show installed packages
    log_info("Installed NVIDIA packages:")
    packages = _get_installed_nvidia_packages()
    if packages:
        for pkg_name, pkg_version in packages:
            log_success(f"  {pkg_name} ({pkg_version})")
        results["packages_ok"] = True
    else:
        log_warn("No NVIDIA packages found")

    # 2. Check held packages
    log_info("Package hold status:")
    try:
        held_output = subprocess.run(
            "apt-mark showhold 2>/dev/null",
            shell=True, capture_output=True, text=True,
        )
        held_nvidia: list[str] = []
        if held_output.returncode == 0:
            for line in held_output.stdout.splitlines():
                if "nvidia" in line.lower():
                    held_nvidia.append(line.strip())

        if held_nvidia:
            for pkg in held_nvidia:
                log_success(f"  [HELD] {pkg}")
            results["holds_ok"] = True
        else:
            if dry_run:
                log_info("  No packages currently held (would be set in fix mode)")
            else:
                log_warn("  No NVIDIA packages are held")
    except OSError:
        log_warn("  Could not check hold status")

    # 3. Check APT pin file
    log_info("APT preferences for NVIDIA:")
    pin_path = "/etc/apt/preferences.d/nvidia-pin"
    if os.path.isfile(pin_path):
        log_success(f"  Pin file exists: {pin_path}")
        try:
            with open(pin_path, "r") as fh:
                for line in fh:
                    log_info(f"    {line.rstrip()}")
        except OSError:
            pass
        results["pin_file_ok"] = True
    else:
        if dry_run:
            log_info("  Pin file would be created in fix mode")
        else:
            log_warn(f"  Pin file does not exist: {pin_path}")

    # 4. Check unattended-upgrades
    log_info("Unattended-upgrades NVIDIA status:")
    config_path = "/etc/apt/apt.conf.d/50unattended-upgrades"
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r") as fh:
                content = fh.read()
            if "nvidia" in content.lower():
                log_success("  NVIDIA is in unattended-upgrades blacklist")
                for line in content.splitlines():
                    if "nvidia" in line.lower():
                        log_info(f"    {line.strip()}")
                results["unattended_ok"] = True
            else:
                log_warn("  NVIDIA is NOT in unattended-upgrades blacklist")
                log_info('  Recommendation: Add \'"nvidia-*";\' to Package-Blacklist')
        except OSError:
            log_warn("  Could not read unattended-upgrades config")
    else:
        log_info("  unattended-upgrades not configured")
        results["unattended_ok"] = True  # Not applicable, so not a failure

    return results


# Directories to scan for NVIDIA libraries
_NVIDIA_LIB_DIRS = [
    "/usr/lib/x86_64-linux-gnu",
    "/usr/lib64",
    "/usr/lib/i386-linux-gnu",
    "/usr/lib",
    "/lib/x86_64-linux-gnu",
    "/lib",
]

# NVIDIA library base names (without .so suffix) that may have versioned copies
_NVIDIA_LIB_BASES = [
    "libnvidia-encode", "libnvidia-decode", "libnvidia-fbc",
    "libnvidia-ml", "libnvidia-opencl", "libnvidia-opticalflow",
    "libnvidia-ptxjitcompiler", "libnvidia-allocator", "libnvidia-cfg",
    "libnvidia-glcore", "libnvidia-glsi", "libnvidia-glvkspirv",
    "libnvidia-gpucomp", "libnvidia-tls", "libnvidia-nvvm",
    "libnvidia-ngx", "libnvidia-api", "libnvidia-vulkan-producer",
    "libcuda", "libcudadebugger", "libnvcuvid",
]


def cleanup_stale_nvidia_libraries(current_version: str, dry_run: bool = True) -> dict[str, list[str]]:
    """Find and remove NVIDIA shared libraries from old driver versions.

    After driver upgrades, old versioned .so files (e.g. libnvidia-encode.so.565.57.01)
    may remain on disk.  These confuse the dynamic linker and the NVIDIA container
    runtime, causing NVENC failures inside Docker containers.

    Args:
        current_version: The running driver version to keep (e.g. '590.48.01').
        dry_run: If True (default), only report findings without modifying anything.

    Returns:
        Dict with keys 'stale_files' and 'stale_symlinks' listing what was found/removed.
    """
    import glob as globmod

    stale_files: list[str] = []
    stale_symlinks: list[str] = []

    for lib_dir in _NVIDIA_LIB_DIRS:
        if not os.path.isdir(lib_dir):
            continue

        # Find all versioned NVIDIA .so files (pattern: libXXX.so.VERSION)
        for base in _NVIDIA_LIB_BASES:
            pattern = os.path.join(lib_dir, f"{base}.so.*.*.*")
            for filepath in globmod.glob(pattern):
                # Extract the version from the filename
                ver_match = re.search(r'\.so\.(\d+\.\d+\.\d+)$', filepath)
                if not ver_match:
                    continue
                file_version = ver_match.group(1)
                if file_version == current_version:
                    continue  # This is the current version, keep it

                if os.path.islink(filepath):
                    stale_symlinks.append(filepath)
                else:
                    stale_files.append(filepath)

        # Also find any symlinks in this dir pointing to old versions
        try:
            for entry in os.scandir(lib_dir):
                if not entry.is_symlink():
                    continue
                # Only check nvidia/cuda related symlinks
                name = entry.name
                if not any(name.startswith(base.split("/")[-1]) for base in _NVIDIA_LIB_BASES):
                    continue
                target = os.readlink(entry.path)
                # Check if symlink target contains an old version
                if current_version not in target and re.search(r'\.\d+\.\d+\.\d+', target):
                    # This symlink points to a versioned file that isn't the current version
                    # But only flag it if it's truly broken (target doesn't exist)
                    resolved = os.path.realpath(entry.path)
                    if not os.path.exists(resolved):
                        if entry.path not in stale_symlinks:
                            stale_symlinks.append(entry.path)
        except OSError:
            continue

    if stale_files or stale_symlinks:
        log_warn(f"Found {len(stale_files)} stale library file(s) and "
                 f"{len(stale_symlinks)} stale symlink(s) from old driver versions")
        for path in stale_files:
            log_info(f"  stale file: {path}")
        for path in stale_symlinks:
            log_info(f"  stale link: {path}")

        if not dry_run:
            for path in stale_symlinks:
                try:
                    os.remove(path)
                    log_info(f"  removed symlink: {path}")
                except OSError as exc:
                    log_warn(f"  failed to remove {path}: {exc}")

            for path in stale_files:
                try:
                    os.remove(path)
                    log_info(f"  removed file: {path}")
                except OSError as exc:
                    log_warn(f"  failed to remove {path}: {exc}")

            # Rebuild linker cache
            subprocess.run("ldconfig", shell=True, check=False)
            log_info("Rebuilt dynamic linker cache (ldconfig)")
    else:
        log_info("No stale NVIDIA library files found")

    return {"stale_files": stale_files, "stale_symlinks": stale_symlinks}


def repair_nvidia_symlinks(current_version: str, dry_run: bool = True) -> list[str]:
    """Ensure all NVIDIA .so.1 symlinks point to the current driver version.

    For each known NVIDIA library, verifies that:
      libXXX.so.1 -> libXXX.so.CURRENT_VERSION
      libXXX.so   -> libXXX.so.1

    Args:
        current_version: The running driver version (e.g. '590.48.01').
        dry_run: If True (default), only report problems without fixing.

    Returns:
        List of symlinks that were broken (and fixed if not dry_run).
    """
    repaired: list[str] = []
    primary_dir = "/usr/lib/x86_64-linux-gnu"

    if not os.path.isdir(primary_dir):
        log_warn(f"Library directory {primary_dir} not found")
        return repaired

    for base in _NVIDIA_LIB_BASES:
        versioned_file = os.path.join(primary_dir, f"{base}.so.{current_version}")
        so1_link = os.path.join(primary_dir, f"{base}.so.1")
        so_link = os.path.join(primary_dir, f"{base}.so")

        # Skip if the versioned file for the current driver doesn't exist
        if not os.path.exists(versioned_file):
            continue

        # Check .so.1 symlink
        needs_so1_fix = False
        if os.path.islink(so1_link):
            target = os.readlink(so1_link)
            resolved = os.path.realpath(so1_link)
            if current_version not in target:
                log_warn(f"  {so1_link} -> {target} (should point to {current_version})")
                needs_so1_fix = True
            elif not os.path.exists(resolved):
                log_warn(f"  {so1_link} -> {target} (dangling)")
                needs_so1_fix = True
        elif not os.path.exists(so1_link):
            log_warn(f"  {so1_link} missing")
            needs_so1_fix = True

        if needs_so1_fix:
            repaired.append(so1_link)
            if not dry_run:
                try:
                    if os.path.islink(so1_link):
                        os.remove(so1_link)
                    expected_target = f"{base}.so.{current_version}"
                    os.symlink(expected_target, so1_link)
                    log_info(f"  fixed: {so1_link} -> {expected_target}")
                except OSError as exc:
                    log_warn(f"  failed to fix {so1_link}: {exc}")

        # Check .so symlink (should point to .so.1)
        needs_so_fix = False
        if os.path.islink(so_link):
            target = os.readlink(so_link)
            if target != f"{base}.so.1" and target != so1_link:
                log_warn(f"  {so_link} -> {target} (should point to {base}.so.1)")
                needs_so_fix = True
        elif not os.path.exists(so_link):
            # .so link might not exist for all libraries, only create for encode/decode
            if any(key in base for key in ["encode", "decode", "fbc", "cuda", "nvcuvid", "ml"]):
                log_warn(f"  {so_link} missing")
                needs_so_fix = True

        if needs_so_fix:
            repaired.append(so_link)
            if not dry_run:
                try:
                    if os.path.islink(so_link):
                        os.remove(so_link)
                    expected_target = f"{base}.so.1"
                    os.symlink(expected_target, so_link)
                    log_info(f"  fixed: {so_link} -> {expected_target}")
                except OSError as exc:
                    log_warn(f"  failed to fix {so_link}: {exc}")

    if repaired:
        if not dry_run:
            subprocess.run("ldconfig", shell=True, check=False)
            log_info("Rebuilt dynamic linker cache (ldconfig)")
        else:
            log_warn(f"Found {len(repaired)} symlink(s) needing repair (dry-run, no changes made)")
    else:
        log_info("All NVIDIA library symlinks are correct")

    return repaired


def pin_nvidia_driver_version(major_version: str, dry_run: bool = False) -> bool:
    """Pin the current NVIDIA driver packages to prevent unattended upgrades.

    Performs three layers of protection:
    1. apt-mark hold on all installed NVIDIA packages for this major version
    2. Creates /etc/apt/preferences.d/nvidia-pin with Pin-Priority 1001
    3. Adds NVIDIA to unattended-upgrades blacklist (if configured)

    Args:
        major_version: The driver major version to pin (e.g. '590').
        dry_run: If True, only report what would be done without making changes.

    Returns:
        True if packages were pinned successfully (or would be in dry-run).
    """
    try:
        # Find all installed nvidia packages for this major version
        result = subprocess.run(
            f"dpkg -l 'nvidia-*{major_version}*' '*nvidia*{major_version}*' 2>/dev/null",
            shell=True, capture_output=True, text=True,
        )

        packages_to_hold: list[str] = []
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split()
                # ii = installed, hi = hold-installed (already pinned)
                if len(parts) >= 2 and parts[0] in ("ii", "hi"):
                    packages_to_hold.append(parts[1])

        if not packages_to_hold:
            log_warn(f"No nvidia-{major_version} packages found to pin")
            return False

        # Layer 1: apt-mark hold
        if dry_run:
            log_info(f"[DRY-RUN] Would hold {len(packages_to_hold)} package(s):")
            for pkg in packages_to_hold:
                log_info(f"  would hold: {pkg}")
        else:
            pkg_list = " ".join(packages_to_hold)
            run_command(f"apt-mark hold {pkg_list}", check=False)
            log_info(f"Pinned {len(packages_to_hold)} NVIDIA package(s) to prevent auto-upgrade")
            for pkg in packages_to_hold:
                log_info(f"  held: {pkg}")

        # Layer 2: APT preferences pin file
        create_apt_pin_file(major_version, dry_run=dry_run)

        # Layer 3: Unattended-upgrades blacklist
        manage_unattended_upgrades_blacklist(dry_run=dry_run)

        return True

    except Exception as e:
        log_warn(f"Could not pin NVIDIA packages: {e}")
        return False


def full_nvidia_cleanup(dry_run: bool = True) -> bool:
    """Run comprehensive NVIDIA driver cleanup.

    Orchestrates all cleanup steps:
    1. Audit installed NVIDIA packages (categorize current/old/other)
    2. Audit NVIDIA APT repository sources
    3. Remove old driver APT packages
    4. Remove stale versioned library files
    5. Repair broken symlinks
    6. Pin the current driver version (apt-mark hold + pin file + unattended-upgrades)
    7. Verify final state

    Args:
        dry_run: If True (default), only report issues without making changes.

    Returns:
        True if any issues were found (and fixed if not dry_run).
    """
    mode_label = "DRY RUN" if dry_run else "FIXING"
    log_step(f"Running full NVIDIA driver cleanup ({mode_label})...")

    current_version = get_running_driver_version()
    if not current_version:
        log_warn("Cannot determine running NVIDIA driver version via nvidia-smi")
        log_warn("Skipping library and symlink cleanup (driver version required)")
        # Still try package cleanup since it doesn't need the version
        return cleanup_old_nvidia_drivers()

    log_info(f"Running driver version: {current_version}")
    major = current_version.split(".")[0]
    found_issues = False

    # Step 1: Audit installed packages
    log_step("Step 1/7: Auditing installed NVIDIA packages...")
    audit_result = audit_nvidia_packages(current_major=major)
    if audit_result["old"]:
        found_issues = True

    # Step 2: Audit repository sources
    log_step("Step 2/7: Checking NVIDIA package sources...")
    audit_nvidia_repos()

    # Step 3: Remove old driver packages
    log_step("Step 3/7: Checking for old driver packages...")
    if cleanup_old_nvidia_drivers():
        found_issues = True

    # Step 4: Remove stale library files
    log_step("Step 4/7: Scanning for stale library files...")
    result = cleanup_stale_nvidia_libraries(current_version, dry_run=dry_run)
    if result["stale_files"] or result["stale_symlinks"]:
        found_issues = True

    # Step 5: Repair symlinks
    log_step("Step 5/7: Auditing NVIDIA library symlinks...")
    broken = repair_nvidia_symlinks(current_version, dry_run=dry_run)
    if broken:
        found_issues = True

    # Step 6: Pin driver version
    log_step("Step 6/7: Pinning driver version to prevent auto-upgrades...")
    pin_nvidia_driver_version(major, dry_run=dry_run)

    # Step 7: Verify final state
    log_step("Step 7/7: Verifying final state...")
    verify_nvidia_cleanup_state(dry_run=dry_run)

    if found_issues:
        if dry_run:
            log_warn("Issues found. Run cleanup with dry_run=False to fix them.")
        else:
            log_success("Cleanup complete. All issues resolved.")
    else:
        log_success("System is clean. No stale drivers or libraries found.")

    return found_issues


def detect_gpu_vendors() -> list[str]:
    """Detect GPU vendors present in the system via lspci.

    Returns:
        List of vendor identifiers found: 'nvidia', 'intel', 'amd'.
        May contain multiple entries on systems with both dGPU and iGPU.
    """
    vendors: list[str] = []
    try:
        result = subprocess.run(
            "lspci 2>/dev/null | grep -iE 'vga|3d|display'",
            shell=True, capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout:
            text = result.stdout.lower()
            if "nvidia" in text:
                vendors.append("nvidia")
            if "intel" in text:
                vendors.append("intel")
            if "amd" in text or "radeon" in text:
                vendors.append("amd")
    except OSError:
        pass
    return vendors


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


def write_egl_icd_default() -> None:
    """Create an EGL-based NVIDIA ICD JSON as the default Vulkan ICD.

    The standard NVIDIA ICD points to libGLX_nvidia.so.0, which some
    statically-linked FFmpeg builds cannot use for Vulkan initialisation
    (fails with VK_ERROR_INCOMPATIBLE_DRIVER).  Using libEGL_nvidia.so.0
    works universally.

    The Vulkan api_version is read from the driver-installed ICD at
    /usr/share/vulkan/icd.d/nvidia_icd.json so it stays in sync with
    the installed driver.  Falls back to a safe default if unreadable.

    Creates /etc/vulkan/icd.d/ and the ICD file if they do not exist.
    """
    import json as _json

    # Search multiple paths for the EGL library
    egl_found = False
    for lib_dir in _NVIDIA_LIB_DIRS:
        candidate = os.path.join(lib_dir, "libEGL_nvidia.so.0")
        if os.path.exists(candidate):
            egl_found = True
            break

    # Also check via ldconfig if not found on disk
    if not egl_found:
        try:
            result = subprocess.run(
                "ldconfig -p | grep libEGL_nvidia.so.0",
                shell=True, capture_output=True, text=True,
            )
            if result.returncode == 0 and "libEGL_nvidia" in result.stdout:
                egl_found = True
        except OSError:
            pass

    if not egl_found:
        log_warn("Could not write default EGL ICD: libEGL_nvidia.so.0 not found on system")
        return

    # Read api_version from the driver-shipped ICD
    api_version = "1.3.275"
    for src in [
        "/usr/share/vulkan/icd.d/nvidia_icd.json",
        "/usr/share/vulkan/icd.d/nvidia_icd.x86_64.json",
        "/etc/vulkan/icd.d/nvidia_icd.json",
    ]:
        try:
            with open(src, "r") as fh:
                data = _json.load(fh)
            existing_lib = data.get("ICD", {}).get("library_path", "")
            if existing_lib == "libEGL_nvidia.so.0":
                ver = data.get("ICD", {}).get("api_version", "")
                if re.match(r"^\d+\.\d+\.\d+", ver):
                    log_info(f"Default NVIDIA EGL ICD already configured ({src}, api_version {ver})")
                    return
            ver = data.get("ICD", {}).get("api_version", "")
            if re.match(r"^\d+\.\d+\.\d+", ver):
                api_version = ver
                break
        except (OSError, _json.JSONDecodeError, KeyError):
            continue

    icd_dir = "/etc/vulkan/icd.d"
    icd_path = os.path.join(icd_dir, "nvidia_icd.json")
    icd_content = (
        "{\n"
        '  "file_format_version": "1.0.1",\n'
        '  "ICD": {\n'
        '    "library_path": "libEGL_nvidia.so.0",\n'
        f'    "api_version": "{api_version}"\n'
        "  }\n"
        "}\n"
    )

    try:
        os.makedirs(icd_dir, exist_ok=True)
        with open(icd_path, "w") as fh:
            fh.write(icd_content)
        log_info(f"Wrote default NVIDIA EGL ICD: {icd_path} (api_version {api_version})")
    except OSError as exc:
        log_warn(f"Could not write {icd_path}: {exc}")
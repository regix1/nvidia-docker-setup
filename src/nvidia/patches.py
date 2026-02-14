"""NVIDIA driver patches for NVENC and NvFBC"""

import glob
import re
import subprocess
import tempfile
import os
from typing import Optional

from utils.logging import log_info, log_step, log_warn, log_success, log_error
from utils.prompts import prompt_yes_no
from utils.system import run_command


SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'scripts'
)

# Regex that matches a valid NVIDIA driver version string (e.g. 580.126.09)
_VERSION_PATTERN = re.compile(r'^[0-9]+\.[0-9]+')


def apply_nvidia_patches() -> None:
    """Apply NVIDIA patches for unlimited NVENC sessions"""
    log_step("NVIDIA NVENC & NvFBC unlimited sessions patch...")

    if not prompt_yes_no("Would you like to patch NVIDIA drivers to remove NVENC session limit?"):
        return

    _apply_nvenc_patch()

    if prompt_yes_no("Would you also like to patch for NvFBC support (useful for OBS)?"):
        _apply_nvfbc_patch()


def _nvidia_smi_works() -> bool:
    """Check whether nvidia-smi can successfully query the driver.

    Returns False if nvidia-smi is missing, exits non-zero, or reports a
    driver/library version mismatch (common after upgrading without reboot).
    """
    try:
        result = subprocess.run(
            "nvidia-smi --query-gpu=driver_version --format=csv,noheader",
            shell=True,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False
        output = result.stdout.strip()
        if not output:
            return False
        # After tr -d of whitespace, a mismatch error becomes a long non-version string
        if "mismatch" in output.lower() or "failed" in output.lower():
            return False
        return bool(_VERSION_PATTERN.match(output))
    except OSError:
        return False


def _needs_reboot() -> bool:
    """Check if nvidia-smi indicates a driver/library version mismatch.

    This happens when the userspace libraries have been upgraded but the
    kernel module is still the old version -- a reboot is required.
    """
    try:
        result = subprocess.run(
            "nvidia-smi",
            shell=True,
            capture_output=True,
            text=True,
        )
        combined = result.stdout + result.stderr
        return "Driver/library version mismatch" in combined
    except OSError:
        return False


def _detect_driver_version() -> Optional[str]:
    """Detect the installed NVIDIA driver version using multiple fallback methods.

    Tries the following sources in order and returns the first valid version
    string found:
        1. nvidia-smi query
        2. libnvidia-encode.so.* filename on disk
        3. modinfo nvidia kernel module
        4. dpkg package database

    Returns:
        Driver version string (e.g. "580.126.09") or None if all methods fail.
    """
    # Method 1: nvidia-smi
    try:
        result = subprocess.run(
            "nvidia-smi --query-gpu=driver_version --format=csv,noheader",
            shell=True,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            ver = result.stdout.strip()
            if ver and _VERSION_PATTERN.match(ver):
                return ver
    except OSError:
        pass

    # Method 2: Parse from installed libnvidia-encode.so filename
    version_from_lib = _detect_version_from_library()
    if version_from_lib is not None:
        return version_from_lib

    # Method 3: modinfo nvidia
    try:
        result = subprocess.run(
            "modinfo nvidia",
            shell=True,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("version:"):
                    ver = line.split(None, 1)[1].strip() if len(line.split(None, 1)) > 1 else ""
                    if ver and _VERSION_PATTERN.match(ver):
                        return ver
    except OSError:
        pass

    # Method 4: dpkg
    try:
        result = subprocess.run(
            "dpkg -l 'nvidia-driver-*'",
            shell=True,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split()
                if (
                    len(parts) >= 3
                    and parts[0] == "ii"
                    and re.match(r'^nvidia-driver-[0-9]+$', parts[1])
                ):
                    match = re.match(r'^[0-9]+\.[0-9]+\.[0-9]+', parts[2])
                    if match:
                        return match.group(0)
    except OSError:
        pass

    return None


def _detect_version_from_library() -> Optional[str]:
    """Parse driver version from the libnvidia-encode.so filename on disk.

    Scans common library directories for libnvidia-encode.so.X.Y.Z and
    extracts the version from the filename.
    """
    search_dirs = [
        "/usr/lib/x86_64-linux-gnu",
        "/usr/lib64",
        "/usr/lib",
        "/lib/x86_64-linux-gnu",
        "/lib64",
        "/lib",
    ]

    for search_dir in search_dirs:
        pattern = os.path.join(search_dir, "libnvidia-encode.so.*.*.*")
        matches = glob.glob(pattern)
        if matches:
            # Extract version from first match
            filename = os.path.basename(matches[0])
            ver_match = re.search(r'\.so\.([0-9]+\.[0-9]+\.[0-9]+)', filename)
            if ver_match:
                return ver_match.group(1)

    return None


def _apply_nvenc_patch() -> None:
    """Apply NVENC session limit patch using our binary patcher.

    Uses Python3-based anchor scanning to precisely locate and patch the
    session-limit check in libnvidia-encode.so.  Automatically detects
    the byte-pattern variant for the installed driver version.

    When nvidia-smi is broken (e.g. after driver upgrade without reboot),
    detects the version via fallback methods and passes it to the script
    with the -d flag.
    """
    script_path = os.path.join(SCRIPTS_DIR, 'nvenc-patch.sh')

    if os.path.isfile(script_path):
        log_info("Applying NVENC session limit patch...")

        # Determine if nvidia-smi is functional
        smi_ok = _nvidia_smi_works()
        version_override: Optional[str] = None

        if not smi_ok:
            reboot_needed = _needs_reboot()
            if reboot_needed:
                log_warn(
                    "nvidia-smi reports driver/library version mismatch "
                    "(kernel module is stale after driver upgrade)"
                )
            else:
                log_warn("nvidia-smi is not working -- attempting fallback version detection")

            version_override = _detect_driver_version()
            if version_override is not None:
                log_info(f"Detected driver version via fallback: {version_override}")
            else:
                log_error("Could not detect driver version via any method")
                log_warn("Please reboot and re-run, or pass version manually")
                return

        try:
            run_command(f"chmod +x {script_path}")
            if version_override is not None:
                run_command(f"bash {script_path} -v -d {version_override}")
            else:
                run_command(f"bash {script_path} -v")
            log_success("NVENC session limit patch applied!")
            return
        except subprocess.CalledProcessError as e:
            log_warn(f"Custom patch script failed: {e}")
            log_info("Trying upstream keylase/nvidia-patch as fallback...")
        except OSError as e:
            log_warn(f"Custom patch script failed: {e}")
            log_info("Trying upstream keylase/nvidia-patch as fallback...")

    # Fallback: upstream keylase/nvidia-patch
    _apply_upstream_script("patch.sh", "NVENC")


def _apply_nvfbc_patch() -> None:
    """Apply NvFBC patch for OBS / screen-capture support"""
    _apply_upstream_script("patch-fbc.sh", "NvFBC")


def _apply_upstream_script(script_name: str, label: str) -> None:
    """Clone keylase/nvidia-patch and run the given script.

    The upstream keylase scripts use nvidia-smi internally and do not
    accept a version override flag.  If nvidia-smi is broken (version
    mismatch after driver upgrade), we skip the upstream script and
    warn the user to reboot first.
    """
    # Check if nvidia-smi is functional -- upstream scripts depend on it
    if not _nvidia_smi_works():
        reboot_needed = _needs_reboot()
        if reboot_needed:
            log_warn(
                f"Skipping upstream {label} patch: nvidia-smi reports "
                "driver/library version mismatch"
            )
            log_warn(
                "The upstream keylase/nvidia-patch script requires a working "
                "nvidia-smi and does not accept a version override"
            )
            log_warn("Please reboot to load the new kernel module, then re-run this tool")
        else:
            log_warn(
                f"Skipping upstream {label} patch: nvidia-smi is not functional"
            )
            log_warn("Please ensure NVIDIA drivers are properly installed and reboot if needed")
        return

    log_info(f"Applying {label} patch via upstream keylase/nvidia-patch...")

    with tempfile.TemporaryDirectory() as tmp:
        original_dir = os.getcwd()
        try:
            os.chdir(tmp)
            run_command("git clone https://github.com/keylase/nvidia-patch.git .")
            run_command(f"chmod +x {script_name}")
            run_command(f"bash ./{script_name}")
            log_success(f"{label} patch applied!")
        except subprocess.CalledProcessError as e:
            log_warn(f"{label} patching failed: {e}")
            log_warn("You can manually apply the patch later if needed")
        except OSError as e:
            log_warn(f"{label} patching failed: {e}")
            log_warn("You can manually apply the patch later if needed")
        finally:
            os.chdir(original_dir)

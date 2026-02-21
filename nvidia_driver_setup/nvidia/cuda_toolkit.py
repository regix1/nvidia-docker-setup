"""Host CUDA Toolkit installation via NVIDIA APT repository.

Installs the NVIDIA CUDA Toolkit on the host (nvcc, development
libraries, headers) with optional cuDNN.  Separate from cuda.py
which handles Docker container CUDA image selection.
"""

import json
import os
import re
from typing import Optional

from ..utils.logging import log_info, log_warn, log_error, log_step, log_success
from ..utils.prompts import prompt_yes_no, prompt_choice
from ..utils.system import run_command, AptManager, get_os_info

# Re-use the driver-compatibility mapping from the container CUDA module.
from .cuda import _MIN_DRIVER

# Profile script path for persistent environment setup.
_CUDA_PROFILE_SCRIPT = "/etc/profile.d/cuda.sh"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _detect_cuda_toolkit() -> Optional[str]:
    """Check if the CUDA Toolkit is installed on the host.

    Returns:
        Version string (e.g. "12.8.0") if installed, None otherwise.
    """
    # Try nvcc first
    try:
        output = run_command("nvcc --version 2>/dev/null", capture_output=True, check=False)
        if output and "release" in output.lower():
            # Parse "Cuda compilation tools, release 12.8, V12.8.93"
            match = re.search(r"release\s+([\d.]+)", output)
            if match:
                return match.group(1)
    except Exception:
        pass

    # Fallback: version.json in /usr/local/cuda
    version_json = "/usr/local/cuda/version.json"
    if os.path.exists(version_json):
        try:
            with open(version_json, "r") as fh:
                data = json.load(fh)
            ver = data.get("cuda", {}).get("version")
            if ver:
                return ver
        except Exception:
            pass

    # Fallback: version.txt
    version_txt = "/usr/local/cuda/version.txt"
    if os.path.exists(version_txt):
        try:
            with open(version_txt, "r") as fh:
                content = fh.read()
            match = re.search(r"CUDA Version\s+([\d.]+)", content)
            if match:
                return match.group(1)
        except Exception:
            pass

    return None


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def _get_available_versions() -> list[str]:
    """Return available CUDA Toolkit versions from the _MIN_DRIVER mapping.

    Returns:
        Sorted list of version strings (newest first).
    """
    return sorted(
        _MIN_DRIVER.keys(),
        key=lambda v: [int(x) for x in v.split(".")],
        reverse=True,
    )


def _classify_version(version: str) -> str:
    """Return a short description tag for a CUDA version."""
    major, minor, _patch = (int(x) for x in version.split("."))
    if major >= 13:
        return "Latest - RTX 50 series / Blackwell"
    if (major, minor) >= (12, 8):
        return "Recent stable - Broad GPU support"
    if (major, minor) >= (12, 4):
        return "Stable - RTX 40 series optimized"
    if (major, minor) >= (12, 0):
        return "Mature - Enterprise ready"
    if major == 11:
        return "Legacy - Proven stability"
    return "Older legacy"


def _check_driver_compatibility(cuda_version: str) -> bool:
    """Check if the installed NVIDIA driver meets the minimum requirement.

    Args:
        cuda_version: The CUDA version to install (e.g. "12.8.0").

    Returns:
        True if the driver is compatible (or couldn't be checked).
    """
    min_driver = _MIN_DRIVER.get(cuda_version)
    if not min_driver:
        log_warn(f"No minimum driver info for CUDA {cuda_version}")
        return True

    try:
        output = run_command(
            "nvidia-smi --query-gpu=driver_version --format=csv,noheader",
            capture_output=True, check=False,
        )
        if not output:
            log_warn("Could not detect installed driver version")
            return True

        installed = output.strip()

        # Compare version tuples
        def _ver_tuple(v: str) -> tuple[int, ...]:
            return tuple(int(x) for x in v.split("."))

        if _ver_tuple(installed) >= _ver_tuple(min_driver):
            log_info(f"Driver {installed} meets minimum {min_driver} for CUDA {cuda_version}")
            return True

        log_error(
            f"Installed driver {installed} is below the minimum {min_driver} "
            f"required for CUDA {cuda_version}."
        )
        log_error("Please update your NVIDIA driver first.")
        return False

    except Exception:
        log_warn("Could not verify driver compatibility")
        return True


# ---------------------------------------------------------------------------
# Repository setup
# ---------------------------------------------------------------------------

def _setup_nvidia_cuda_repository() -> None:
    """Add the NVIDIA CUDA APT repository via the cuda-keyring package."""
    os_info = get_os_info()
    version_id = os_info.get("VERSION_ID", "22.04")
    os_ver = version_id.replace(".", "")  # "22.04" -> "2204"

    keyring_url = (
        f"https://developer.download.nvidia.com/compute/cuda/repos/"
        f"ubuntu{os_ver}/x86_64/cuda-keyring_1.1-1_all.deb"
    )
    keyring_deb = "/tmp/cuda-keyring.deb"

    log_info("Downloading NVIDIA CUDA keyring...")
    run_command(f"wget -qO {keyring_deb} {keyring_url}")

    log_info("Installing CUDA keyring package...")
    run_command(f"dpkg -i {keyring_deb}")

    # Clean up
    try:
        os.unlink(keyring_deb)
    except OSError:
        pass

    # Force apt to re-read sources
    AptManager.reset_cache()


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------

def _install_cuda_toolkit_packages(version: str) -> None:
    """Install the CUDA Toolkit packages for the given version.

    Args:
        version: CUDA version string (e.g. "12.8.0").
    """
    major, minor, _patch = version.split(".")
    package = f"cuda-toolkit-{major}-{minor}"

    apt = AptManager()
    log_info(f"Installing {package}...")
    apt.install(package)


def _offer_cudnn_install(version: str) -> None:
    """Optionally install cuDNN for the given CUDA version.

    Args:
        version: CUDA version string (e.g. "12.8.0").
    """
    major = version.split(".")[0]
    major_int = int(major)

    if major_int < 12:
        log_info("cuDNN for CUDA < 12 is bundled differently; skipping automatic install.")
        return

    print()
    if prompt_yes_no("Install cuDNN (deep learning primitives library)?"):
        package = f"cudnn9-cuda-{major}"
        apt = AptManager()
        log_info(f"Installing {package}...")
        try:
            apt.install(package)
            log_success("cuDNN installed successfully")
        except Exception as exc:
            log_warn(f"cuDNN installation failed: {exc}")
            log_info("You can install it manually later with:")
            log_info(f"  apt install {package}")


# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------

def _configure_cuda_environment() -> None:
    """Write a profile.d script so CUDA is on PATH for all users."""
    script_content = (
        '# CUDA Toolkit environment (managed by nvidia-driver-setup)\n'
        'if [ -d /usr/local/cuda/bin ]; then\n'
        '    export PATH="/usr/local/cuda/bin${PATH:+:$PATH}"\n'
        'fi\n'
        'if [ -d /usr/local/cuda/lib64 ]; then\n'
        '    export LD_LIBRARY_PATH="/usr/local/cuda/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n'
        'fi\n'
    )

    log_info(f"Writing CUDA environment script to {_CUDA_PROFILE_SCRIPT}...")
    try:
        with open(_CUDA_PROFILE_SCRIPT, "w") as fh:
            fh.write(script_content)
        os.chmod(_CUDA_PROFILE_SCRIPT, 0o644)
        log_success("CUDA environment configured (effective on next login)")
    except OSError as exc:
        log_warn(f"Could not write {_CUDA_PROFILE_SCRIPT}: {exc}")
        log_info("You can manually add /usr/local/cuda/bin to your PATH")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def _verify_cuda_toolkit() -> bool:
    """Verify the CUDA Toolkit installation.

    Returns:
        True if nvcc is found and reports a version.
    """
    log_info("Verifying CUDA Toolkit installation...")

    # Source the profile script to get PATH, then check nvcc
    output = run_command(
        "bash -c 'source /etc/profile.d/cuda.sh 2>/dev/null; nvcc --version' 2>/dev/null",
        capture_output=True, check=False,
    )
    if output and "release" in output.lower():
        log_success("nvcc is working")
        # Print the version line
        for line in output.splitlines():
            if "release" in line.lower():
                log_info(f"  {line.strip()}")
                break
        return True

    log_warn("nvcc not found on PATH (may need a new shell or reboot)")
    return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def install_cuda_toolkit() -> None:
    """Install the NVIDIA CUDA Toolkit on the host.

    Main entry point called from the CLI menu.
    """
    log_step("CUDA Toolkit Installation")
    log_info("This installs the CUDA compiler (nvcc), development libraries,")
    log_info("and headers on the host.  Separate from CUDA container images.\n")

    # Check if already installed
    existing = _detect_cuda_toolkit()
    if existing:
        log_info(f"CUDA Toolkit is already installed (version: {existing})")
        if not prompt_yes_no("Reinstall / update CUDA Toolkit?"):
            return

    # Build version list from _MIN_DRIVER
    versions = _get_available_versions()
    choices: list[str] = []
    version_list: list[str] = []

    for ver in versions:
        tag = _classify_version(ver)
        min_drv = _MIN_DRIVER.get(ver, "")
        driver_note = f"  (min driver: {min_drv})" if min_drv else ""
        choices.append(f"{ver} - {tag}{driver_note}")
        version_list.append(ver)

    print("\nAvailable CUDA Toolkit versions:")
    for i, choice in enumerate(choices, 1):
        recommended = " (recommended)" if i == 1 else ""
        print(f"  {i}. {choice}{recommended}")
    print()

    choice_idx = prompt_choice(
        "Select CUDA Toolkit version",
        [f"Option {i}" for i in range(1, len(choices) + 1)],
        default=0,
    )
    selected_version = version_list[choice_idx]
    log_info(f"Selected CUDA Toolkit version: {selected_version}")

    # Check driver compatibility before proceeding
    if not _check_driver_compatibility(selected_version):
        if not prompt_yes_no("Continue anyway? (installation may fail)"):
            return

    # Set up NVIDIA CUDA repository and install
    try:
        log_info("Setting up NVIDIA CUDA repository...")
        _setup_nvidia_cuda_repository()

        # Install the toolkit
        _install_cuda_toolkit_packages(selected_version)
    except Exception as exc:
        log_error(f"CUDA Toolkit installation failed: {exc}")
        log_info("Check your internet connection and try again.")
        return

    # Configure environment
    _configure_cuda_environment()

    # Offer cuDNN
    _offer_cudnn_install(selected_version)

    # Verify
    _verify_cuda_toolkit()

    # Summary
    print()
    log_success(f"CUDA Toolkit {selected_version} installed successfully!")
    print()
    log_info("Included components:")
    log_info("  - nvcc (CUDA compiler)")
    log_info("  - CUDA runtime and development libraries")
    log_info("  - CUDA headers and samples")
    log_info("  - cuBLAS, cuFFT, cuRAND, cuSOLVER, cuSPARSE")
    log_info("  - NVIDIA Nsight tools")
    print()
    log_info("Quick test:  nvcc --version")
    log_info("CUDA path:   /usr/local/cuda")
    log_info("Note: Open a new shell or run 'source /etc/profile.d/cuda.sh' to use nvcc")

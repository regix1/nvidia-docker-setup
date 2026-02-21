"""Vulkan SDK installation via LunarG APT repository.

Installs the LunarG Vulkan SDK on the host for development
(validation layers, SPIR-V tools, headers, vulkaninfo).

Fetches available versions from the LunarG API (like CUDA does
from Docker Hub), with offline fallback to configs/vulkan_versions.json.
"""

import json
import os
import re
import urllib.request
from typing import Optional

from ..utils.logging import log_info, log_warn, log_error, log_step, log_success
from ..utils.prompts import prompt_yes_no, prompt_choice, prompt_input
from ..utils.system import run_command, AptManager, get_os_info

_LUNARG_VERSIONS_URL = "https://vulkan.lunarg.com/sdk/versions/linux.json"
_LUNARG_LATEST_URL = "https://vulkan.lunarg.com/sdk/latest/linux.json"
_LUNARG_TIMEOUT = 15  # seconds

# APT repo base URL -- repo directories use 3-part versions (e.g. 1.4.309)
_LUNARG_PACKAGES_BASE = "https://packages.lunarg.com/vulkan"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _detect_vulkan_sdk() -> Optional[str]:
    """Check if the Vulkan SDK is already installed.

    Returns:
        Version string if installed, None otherwise.
    """
    # Try dpkg first (most reliable for APT installs)
    try:
        output = run_command(
            "dpkg -s vulkan-sdk 2>/dev/null | grep '^Version:'",
            capture_output=True, check=False,
        )
        if output and "Version:" in output:
            return output.split("Version:")[1].strip()
    except Exception:
        pass

    # Fallback: VULKAN_SDK environment variable
    sdk_path = os.environ.get("VULKAN_SDK")
    if sdk_path and os.path.isdir(sdk_path):
        match = re.search(r"(\d+\.\d+\.\d+(?:\.\d+)?)", sdk_path)
        if match:
            return match.group(1)
        return "unknown"

    return None


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def _to_apt_version(version: str) -> str:
    """Convert a 4-part API version to the 3-part APT repo version.

    The LunarG API returns versions like '1.4.309.0' but the APT
    repository directories use '1.4.309' (3 parts).

    Args:
        version: Version string from the API (e.g. "1.4.309.0").

    Returns:
        3-part version string (e.g. "1.4.309").
    """
    parts = version.split(".")
    if len(parts) >= 3:
        return ".".join(parts[:3])
    return version


def _classify_vulkan_version(version: str) -> str:
    """Return a short description tag based on the Vulkan version family."""
    parts = version.split(".")
    try:
        major, minor = int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return ""
    if (major, minor) >= (1, 4):
        return "Vulkan 1.4"
    if (major, minor) >= (1, 3):
        return "Vulkan 1.3"
    if (major, minor) >= (1, 2):
        return "Vulkan 1.2"
    return "Vulkan 1.1 or earlier"


# ---------------------------------------------------------------------------
# Version fetching (live from LunarG API)
# ---------------------------------------------------------------------------

def _get_vulkan_sdk_versions() -> Optional[list[str]]:
    """Query the LunarG API for available Vulkan SDK versions.

    Returns:
        List of version strings (newest first), or None on failure.
    """
    try:
        req = urllib.request.Request(
            _LUNARG_VERSIONS_URL,
            headers={"User-Agent": "nvidia-driver-setup/1.0"},
        )
        resp = urllib.request.urlopen(req, timeout=_LUNARG_TIMEOUT)
        data = json.loads(resp.read())

        if isinstance(data, list) and data:
            # API returns versions newest-first already
            return [str(v) for v in data]
        return None
    except Exception as exc:
        log_warn(f"Could not fetch Vulkan SDK versions: {exc}")
        return None


def _get_latest_vulkan_sdk_version() -> Optional[str]:
    """Query the LunarG API for the latest Vulkan SDK version.

    The API returns ``{"linux": "1.4.341.1"}``.

    Returns:
        Latest version string, or None on failure.
    """
    try:
        req = urllib.request.Request(
            _LUNARG_LATEST_URL,
            headers={"User-Agent": "nvidia-driver-setup/1.0"},
        )
        resp = urllib.request.urlopen(req, timeout=_LUNARG_TIMEOUT)
        data = json.loads(resp.read())

        # Response is {"linux": "x.y.z.w"}
        if isinstance(data, dict):
            return str(data.get("linux") or data.get("version") or "")  or None
        if isinstance(data, str):
            return data
        if isinstance(data, list) and data:
            return str(data[0])
        return None
    except Exception as exc:
        log_warn(f"Could not fetch latest Vulkan SDK version: {exc}")
        return None


def _load_fallback_versions() -> dict[str, str]:
    """Load Vulkan SDK versions from the local fallback config."""
    config_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..", "configs", "vulkan_versions.json",
    )
    try:
        with open(config_path, "r") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "1.4.313.0": "Latest APT - Vulkan 1.4",
            "1.3.296.0": "Stable - Vulkan 1.3",
            "1.3.283.0": "Previous stable",
            "1.3.268.0": "Legacy stable",
        }


def _check_apt_repo_exists(apt_version: str, codename: str) -> bool:
    """Probe whether the LunarG APT list file exists for a given version.

    Args:
        apt_version: 3-part version (e.g. "1.4.309").
        codename: Ubuntu codename (e.g. "jammy").

    Returns:
        True if the repo list URL is reachable.
    """
    url = (
        f"{_LUNARG_PACKAGES_BASE}/{apt_version}/"
        f"lunarg-vulkan-{apt_version}-{codename}.list"
    )
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "nvidia-driver-setup/1.0"})
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Repository setup
# ---------------------------------------------------------------------------

def _setup_lunarg_repository(apt_version: str, codename: str) -> None:
    """Add the LunarG APT signing key and repository.

    Args:
        apt_version: 3-part Vulkan SDK version (e.g. "1.4.309").
        codename: Ubuntu codename (e.g. "jammy", "noble").
    """
    log_info("Adding LunarG signing key...")
    run_command(
        "wget -qO- https://packages.lunarg.com/lunarg-signing-key-pub.asc "
        "| tee /etc/apt/trusted.gpg.d/lunarg.asc > /dev/null"
    )

    log_info(f"Adding LunarG Vulkan SDK {apt_version} repository for {codename}...")
    list_url = (
        f"{_LUNARG_PACKAGES_BASE}/{apt_version}/"
        f"lunarg-vulkan-{apt_version}-{codename}.list"
    )
    list_dest = f"/etc/apt/sources.list.d/lunarg-vulkan-{apt_version}.list"
    run_command(f"wget -qO {list_dest} {list_url}")

    # Force apt to re-read sources
    AptManager.reset_cache()


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------

def _install_vulkan_sdk_packages() -> None:
    """Install the full Vulkan SDK meta-package."""
    apt = AptManager()
    log_info("Installing Vulkan SDK packages...")
    apt.install("vulkan-sdk")


def _verify_vulkan_sdk() -> bool:
    """Verify the Vulkan SDK installation by running vulkaninfo.

    Returns:
        True if verification passed.
    """
    log_info("Verifying Vulkan SDK installation...")

    output = run_command("vulkaninfo --summary 2>&1", capture_output=True, check=False)
    if output and ("Vulkan Instance Version" in output or "apiVersion" in output):
        log_success("vulkaninfo reports Vulkan is working")
        return True

    # SDK installed but vulkaninfo may need a GPU driver
    log_warn("vulkaninfo could not verify a Vulkan device (driver may need a reboot)")
    return False


def _show_vulkan_sdk_info(version: str) -> None:
    """Display information about the installed Vulkan SDK."""
    print()
    log_success(f"Vulkan SDK {version} installed successfully!")
    print()
    log_info("Included components:")
    log_info("  - Vulkan Loader and validation layers")
    log_info("  - SPIR-V tools (spirv-val, spirv-opt, spirv-cross)")
    log_info("  - Vulkan headers and development libraries")
    log_info("  - vulkaninfo, vkcube (test utilities)")
    log_info("  - glslangValidator (GLSL to SPIR-V compiler)")
    log_info("  - Layer configuration utilities")
    print()
    log_info("Quick test:  vulkaninfo --summary")
    log_info("Cube demo:   vkcube")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def install_vulkan_sdk() -> None:
    """Install the LunarG Vulkan SDK on the host.

    Main entry point called from the CLI menu.
    """
    log_step("Vulkan SDK Installation")

    # Check if already installed
    existing = _detect_vulkan_sdk()
    if existing:
        log_info(f"Vulkan SDK is already installed (version: {existing})")
        if not prompt_yes_no("Reinstall / update Vulkan SDK?"):
            return

    # Get OS codename for the repository URL
    os_info = get_os_info()
    codename = os_info.get("UBUNTU_CODENAME") or os_info.get("VERSION_CODENAME", "")
    if not codename:
        log_error("Could not determine OS codename. Cannot set up LunarG repository.")
        return

    log_info(f"Detected OS codename: {codename}")

    # Fetch available versions from LunarG API
    log_info("Fetching available Vulkan SDK versions...")
    latest = _get_latest_vulkan_sdk_version()
    live_versions = _get_vulkan_sdk_versions()

    if live_versions:
        log_info(f"Found {len(live_versions)} versions from LunarG API.")

        # Build display list with classification
        display_versions = live_versions[:15]
        choices: list[str] = []
        version_list: list[str] = []

        for i, ver in enumerate(display_versions):
            tag = _classify_vulkan_version(ver)
            latest_tag = " (latest)" if latest and ver == latest else ""
            recommended = " (recommended)" if i == 0 else ""
            choices.append(f"{ver} - {tag}{latest_tag}{recommended}")
            version_list.append(ver)

        # Add custom version option (like CUDA does)
        choices.append("Enter custom version")
    else:
        log_warn("Could not fetch live versions, using offline list.")
        fallback = _load_fallback_versions()
        choices = []
        version_list = []
        for ver, desc in fallback.items():
            choices.append(f"{ver} - {desc}")
            version_list.append(ver)

        choices.append("Enter custom version")

    # Display the menu
    print("\nAvailable Vulkan SDK versions:")
    for i, choice in enumerate(choices, 1):
        print(f"  {i}. {choice}")
    print()

    choice_idx = prompt_choice(
        "Select Vulkan SDK version",
        [f"Option {i}" for i in range(1, len(choices) + 1)],
        default=0,
    )

    if choice_idx == len(choices) - 1:  # Custom version option
        selected_version = prompt_input("Enter Vulkan SDK version (e.g., 1.4.309.0)")
        if not selected_version:
            log_info("No version entered, cancelled.")
            return
    else:
        selected_version = version_list[choice_idx]

    log_info(f"Selected Vulkan SDK version: {selected_version}")

    # Convert to the 3-part version used by APT repos
    apt_version = _to_apt_version(selected_version)
    log_info(f"APT repository version: {apt_version}")

    # Check if the APT repo actually exists for this version/codename
    log_info(f"Checking if APT repository exists for {apt_version}/{codename}...")
    if not _check_apt_repo_exists(apt_version, codename):
        log_warn(
            f"No APT repository found for Vulkan SDK {apt_version} on {codename}. "
            f"Not all SDK versions have APT packages (newer versions may require "
            f"the tarball installer from vulkan.lunarg.com)."
        )
        if not prompt_yes_no("Try anyway?"):
            return

    # Set up repository and install (with error handling)
    try:
        _setup_lunarg_repository(apt_version, codename)
        _install_vulkan_sdk_packages()
    except Exception as exc:
        log_error(f"Vulkan SDK installation failed: {exc}")
        log_info("Check your internet connection and verify the selected version is "
                 f"available for {codename}.")
        log_info(f"You can also try installing manually from https://vulkan.lunarg.com/sdk/home")
        return

    # Verify and display info
    if _verify_vulkan_sdk():
        _show_vulkan_sdk_info(selected_version)
    else:
        log_info(f"Vulkan SDK {selected_version} packages installed (verification "
                 f"requires a GPU driver and may need a reboot).")

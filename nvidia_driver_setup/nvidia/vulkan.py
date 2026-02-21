"""Vulkan SDK installation via LunarG tarball.

Installs the LunarG Vulkan SDK on the host for development
(validation layers, SPIR-V tools, headers, vulkaninfo).

Fetches available versions from the LunarG API, downloads the
official tarball, and configures the environment.  APT-based
installation was deprecated by LunarG in May 2025.
"""

import json
import os
import platform
import re
import shutil
import urllib.request
from typing import Optional

from ..utils.logging import log_info, log_warn, log_error, log_step, log_success
from ..utils.prompts import prompt_yes_no, prompt_choice, prompt_input
from ..utils.system import run_command, AptManager, write_egl_icd_default

# LunarG API endpoints
_LUNARG_VERSIONS_URL = "https://vulkan.lunarg.com/sdk/versions/linux.json"
_LUNARG_LATEST_URL = "https://vulkan.lunarg.com/sdk/latest/linux.json"
_LUNARG_TIMEOUT = 15

# Tarball download endpoints
_LUNARG_DOWNLOAD_BASE = "https://sdk.lunarg.com/sdk/download"
_LUNARG_SHA_BASE = "https://sdk.lunarg.com/sdk/sha"

# Installation paths
_VULKAN_SDK_BASE = "/opt/vulkan-sdk"
_VULKAN_PROFILE_SCRIPT = "/etc/profile.d/vulkan-sdk.sh"
_DOWNLOAD_PATH = "/tmp/vulkan_sdk.tar.xz"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _get_arch() -> str:
    """Return the platform subdirectory used inside the SDK tarball."""
    machine = platform.machine()
    if machine in ("x86_64", "AMD64", "x86-64"):
        return "x86_64"
    if machine in ("aarch64", "arm64"):
        return "aarch64"
    return machine


def _detect_vulkan_sdk() -> Optional[str]:
    """Check if the Vulkan SDK is already installed.

    Returns:
        Version string if installed, None otherwise.
    """
    # Check tarball install (current symlink)
    current_link = os.path.join(_VULKAN_SDK_BASE, "current")
    if os.path.islink(current_link):
        target = os.readlink(current_link)
        name = os.path.basename(target)
        if re.match(r"\d+\.\d+\.\d+", name):
            return name

    # Check for any version directory in the install base
    if os.path.isdir(_VULKAN_SDK_BASE):
        try:
            dirs = [
                e.name for e in os.scandir(_VULKAN_SDK_BASE)
                if e.is_dir() and re.match(r"\d+\.\d+\.\d+", e.name)
            ]
            if dirs:
                dirs.sort(
                    key=lambda v: [int(x) for x in v.split(".")[:3]],
                    reverse=True,
                )
                return dirs[0]
        except OSError:
            pass

    # Legacy: dpkg APT install
    try:
        output = run_command(
            "dpkg -s vulkan-sdk 2>/dev/null | grep '^Version:'",
            capture_output=True, check=False,
        )
        if output and "Version:" in output:
            return output.split("Version:")[1].strip() + " (APT - deprecated)"
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
            return [str(v) for v in data]
        return None
    except Exception as exc:
        log_warn(f"Could not fetch Vulkan SDK versions: {exc}")
        return None


def _get_latest_vulkan_sdk_version() -> Optional[str]:
    """Query the LunarG API for the latest Vulkan SDK version.

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

        if isinstance(data, dict):
            return str(data.get("linux") or data.get("version") or "") or None
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
            "1.4.341.1": "Latest - Vulkan 1.4",
            "1.4.313.0": "Stable - Vulkan 1.4",
            "1.3.296.0": "Stable - Vulkan 1.3",
            "1.3.283.0": "Previous stable",
        }


# ---------------------------------------------------------------------------
# Download and verification
# ---------------------------------------------------------------------------

def _download_tarball(version: str) -> bool:
    """Download the Vulkan SDK tarball.

    Args:
        version: SDK version string (e.g. "1.4.341.0").

    Returns:
        True on success.
    """
    url = f"{_LUNARG_DOWNLOAD_BASE}/{version}/linux/vulkan_sdk.tar.xz?Human=true"
    log_info(f"Downloading Vulkan SDK {version} tarball...")
    try:
        run_command(f"wget -O {_DOWNLOAD_PATH} '{url}'")
        return True
    except Exception as exc:
        log_error(f"Download failed: {exc}")
        return False


def _verify_sha256(version: str) -> bool:
    """Verify SHA256 checksum of the downloaded tarball.

    Args:
        version: SDK version used to look up the expected hash.

    Returns:
        True if checksum matches or verification was skipped.
    """
    sha_url = f"{_LUNARG_SHA_BASE}/{version}/linux/vulkan_sdk.tar.xz.txt"
    try:
        req = urllib.request.Request(
            sha_url,
            headers={"User-Agent": "nvidia-driver-setup/1.0"},
        )
        resp = urllib.request.urlopen(req, timeout=_LUNARG_TIMEOUT)
        expected = resp.read().decode().strip().split()[0]

        log_info("Verifying SHA256 checksum...")
        output = run_command(
            f"sha256sum {_DOWNLOAD_PATH}",
            capture_output=True, check=False,
        )
        if output:
            actual = output.strip().split()[0]
            if actual == expected:
                log_success("SHA256 checksum verified")
                return True
            log_error(
                f"SHA256 mismatch! Expected: {expected[:16]}... "
                f"Got: {actual[:16]}..."
            )
            return False
        log_warn("sha256sum not available, skipping verification")
        return True
    except Exception as exc:
        log_warn(f"Could not verify checksum (continuing): {exc}")
        return True


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------

def _install_runtime_deps() -> None:
    """Install system packages required by SDK tools (vkcube, etc.)."""
    deps = ["libxcb-xinput0", "libxcb-xinerama0", "libxcb-cursor0"]
    log_info("Installing runtime dependencies...")
    apt = AptManager()
    try:
        apt.install(*deps)
    except Exception as exc:
        log_warn(f"Some runtime dependencies could not be installed: {exc}")
        log_info("SDK tools like vkcube may not work without them.")


def _extract_tarball(version: str) -> bool:
    """Extract the SDK tarball to the install location.

    The tarball contains a top-level directory named after the version
    (e.g. ``1.4.341.0/``).  We extract into ``_VULKAN_SDK_BASE`` so
    the result is ``/opt/vulkan-sdk/1.4.341.0/``.

    Args:
        version: Expected version directory name.

    Returns:
        True if extraction succeeded.
    """
    install_dir = os.path.join(_VULKAN_SDK_BASE, version)

    os.makedirs(_VULKAN_SDK_BASE, exist_ok=True)

    # Remove previous install of the same version
    if os.path.isdir(install_dir):
        log_info(f"Removing previous install at {install_dir}...")
        shutil.rmtree(install_dir)

    log_info(f"Extracting to {_VULKAN_SDK_BASE}/...")
    try:
        run_command(f"tar xf {_DOWNLOAD_PATH} -C {_VULKAN_SDK_BASE}")
    except Exception as exc:
        log_error(f"Extraction failed: {exc}")
        return False

    if os.path.isdir(install_dir):
        log_success(f"Extracted to {install_dir}")
        return True

    log_error(f"Expected directory {install_dir} not found after extraction")
    return False


def _create_current_symlink(version: str) -> None:
    """Create or update the ``current`` symlink in the install base."""
    current_link = os.path.join(_VULKAN_SDK_BASE, "current")
    version_dir = os.path.join(_VULKAN_SDK_BASE, version)

    try:
        if os.path.islink(current_link):
            os.remove(current_link)
        elif os.path.exists(current_link):
            os.remove(current_link)
        os.symlink(version_dir, current_link)
        log_info(f"Symlink: {current_link} -> {version_dir}")
    except OSError as exc:
        log_warn(f"Could not create symlink: {exc}")


# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------

def _configure_environment() -> None:
    """Write a profile.d script so the Vulkan SDK is on PATH for all users."""
    arch = _get_arch()
    script_content = (
        '# Vulkan SDK environment (managed by nvidia-driver-setup)\n'
        f'_VULKAN_SDK_DIR="{_VULKAN_SDK_BASE}/current/{arch}"\n'
        'if [ -d "$_VULKAN_SDK_DIR" ]; then\n'
        '    export VULKAN_SDK="$_VULKAN_SDK_DIR"\n'
        '    export PATH="$VULKAN_SDK/bin${PATH:+:$PATH}"\n'
        '    export LD_LIBRARY_PATH="$VULKAN_SDK/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n'
        '    export VK_ADD_LAYER_PATH="$VULKAN_SDK/share/vulkan/explicit_layer.d"\n'
        '    unset VK_LAYER_PATH\n'
        'fi\n'
    )

    log_info(f"Writing Vulkan SDK environment script to {_VULKAN_PROFILE_SCRIPT}...")
    try:
        with open(_VULKAN_PROFILE_SCRIPT, "w") as fh:
            fh.write(script_content)
        os.chmod(_VULKAN_PROFILE_SCRIPT, 0o644)
        log_success("Vulkan SDK environment configured (effective on next login)")
    except OSError as exc:
        log_warn(f"Could not write {_VULKAN_PROFILE_SCRIPT}: {exc}")
        log_info(f"You can manually source: {_VULKAN_SDK_BASE}/current/setup-env.sh")

    # Activate in the current process so tools work immediately
    _activate_environment()


def _activate_environment() -> None:
    """Set Vulkan SDK environment variables in the current process.

    This makes SDK tools (vulkaninfo, glslangValidator, etc.) available
    immediately without requiring the user to open a new shell.
    """
    arch = _get_arch()
    sdk_dir = os.path.join(_VULKAN_SDK_BASE, "current", arch)

    if not os.path.isdir(sdk_dir):
        return

    os.environ["VULKAN_SDK"] = sdk_dir

    sdk_bin = os.path.join(sdk_dir, "bin")
    path = os.environ.get("PATH", "")
    if sdk_bin not in path:
        os.environ["PATH"] = f"{sdk_bin}:{path}"

    sdk_lib = os.path.join(sdk_dir, "lib")
    ld_path = os.environ.get("LD_LIBRARY_PATH", "")
    if sdk_lib not in ld_path:
        os.environ["LD_LIBRARY_PATH"] = f"{sdk_lib}:{ld_path}" if ld_path else sdk_lib

    layer_path = os.path.join(sdk_dir, "share", "vulkan", "explicit_layer.d")
    os.environ["VK_ADD_LAYER_PATH"] = layer_path
    os.environ.pop("VK_LAYER_PATH", None)

    log_info("Vulkan SDK environment activated for current session")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def _verify_vulkan_sdk() -> bool:
    """Verify the Vulkan SDK installation by checking key binaries.

    Returns:
        True if verification passed.
    """
    log_info("Verifying Vulkan SDK installation...")

    arch = _get_arch()
    sdk_bin = os.path.join(_VULKAN_SDK_BASE, "current", arch, "bin")

    for tool in ("vulkaninfo", "glslangValidator", "spirv-val"):
        tool_path = os.path.join(sdk_bin, tool)
        if os.path.isfile(tool_path):
            log_success(f"  {tool} found")
        else:
            log_warn(f"  {tool} not found at {tool_path}")

    # Try running vulkaninfo
    output = run_command(
        f"bash -c 'source {_VULKAN_PROFILE_SCRIPT} 2>/dev/null; "
        f"vulkaninfo --summary' 2>&1",
        capture_output=True, check=False,
    )
    if output and ("Vulkan Instance Version" in output or "apiVersion" in output):
        log_success("vulkaninfo reports Vulkan is working")
        return True

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
    log_info(f"Install path:  {_VULKAN_SDK_BASE}/{version}")
    log_info("Quick test:    vulkaninfo --summary")
    log_info("Cube demo:     vkcube")
    log_info("SDK tools are available in this session and all future shells.")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def install_vulkan_sdk() -> None:
    """Install the LunarG Vulkan SDK on the host.

    Main entry point called from the CLI menu.
    """
    log_step("Vulkan SDK Installation")
    log_info("This installs the LunarG Vulkan SDK via official tarball.")
    log_info("(APT packages were deprecated by LunarG in May 2025)\n")

    # Check if already installed
    existing = _detect_vulkan_sdk()
    if existing:
        log_info(f"Vulkan SDK is already installed (version: {existing})")
        if "(APT" in existing:
            log_warn("The existing APT install is deprecated. "
                     "The new install uses the official tarball.")
            log_info("You can remove the old APT package later with: "
                     "apt remove vulkan-sdk")
        if not prompt_yes_no("Reinstall / update Vulkan SDK?"):
            return

    # Fetch available versions from LunarG API
    log_info("Fetching available Vulkan SDK versions...")
    latest = _get_latest_vulkan_sdk_version()
    live_versions = _get_vulkan_sdk_versions()

    if live_versions:
        log_info(f"Found {len(live_versions)} versions from LunarG API.")

        display_versions = live_versions[:15]
        choices: list[str] = []
        version_list: list[str] = []

        for i, ver in enumerate(display_versions):
            tag = _classify_vulkan_version(ver)
            latest_tag = " (latest)" if latest and ver == latest else ""
            recommended = " (recommended)" if i == 0 else ""
            choices.append(f"{ver} - {tag}{latest_tag}{recommended}")
            version_list.append(ver)

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
        selected_version = prompt_input("Enter Vulkan SDK version (e.g., 1.4.341.0)")
        if not selected_version:
            log_info("No version entered, cancelled.")
            return
    else:
        selected_version = version_list[choice_idx]

    log_info(f"Selected Vulkan SDK version: {selected_version}")

    # Download, verify, extract
    try:
        if not _download_tarball(selected_version):
            log_info("You can manually download from: "
                     "https://vulkan.lunarg.com/sdk/home")
            return

        # Verify checksum
        if not _verify_sha256(selected_version):
            if not prompt_yes_no("SHA256 verification failed. Continue anyway?"):
                try:
                    os.unlink(_DOWNLOAD_PATH)
                except OSError:
                    pass
                return

        # Install runtime dependencies
        _install_runtime_deps()

        # Extract tarball
        if not _extract_tarball(selected_version):
            return
    except Exception as exc:
        log_error(f"Installation failed: {exc}")
        log_info("Check your internet connection and try again.")
        return
    finally:
        # Always clean up the downloaded tarball
        try:
            os.unlink(_DOWNLOAD_PATH)
        except OSError:
            pass

    # Create current symlink
    _create_current_symlink(selected_version)

    # Configure environment
    _configure_environment()

    # Ensure the default NVIDIA Vulkan ICD uses EGL for container compatibility
    write_egl_icd_default()

    # Verify and display info
    _verify_vulkan_sdk()
    _show_vulkan_sdk_info(selected_version)

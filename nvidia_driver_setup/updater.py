"""Self-update module for nvidia-driver-setup.

Detects how the tool was installed (git clone vs pip) and updates accordingly.
"""

import subprocess
import sys
from enum import Enum
from pathlib import Path

from .utils.logging import log_info, log_warn, log_error, log_step, log_success
from .utils.prompts import prompt_yes_no

REPO_URL = "https://github.com/regix1/nvidia-driver-setup.git"


class InstallMethod(Enum):
    """How nvidia-driver-setup was installed."""
    GIT_CLONE = "git_clone"
    PIP = "pip"
    UNKNOWN = "unknown"


def _get_project_root() -> Path:
    """Resolve the project root from this file's location."""
    return Path(__file__).resolve().parent.parent


def detect_install_method() -> InstallMethod:
    """Detect whether we were installed via git clone or pip."""
    project_root = _get_project_root()
    if (project_root / ".git").is_dir():
        return InstallMethod.GIT_CLONE
    return InstallMethod.PIP


def _ensure_origin(cwd: str) -> None:
    """Ensure the git origin remote points to the canonical repo."""
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=cwd, capture_output=True, text=True,
    )
    if result.returncode != 0:
        # No origin remote at all - add it
        subprocess.run(
            ["git", "remote", "add", "origin", REPO_URL],
            cwd=cwd, capture_output=True, text=True,
        )
    elif result.stdout.strip() != REPO_URL:
        subprocess.run(
            ["git", "remote", "set-url", "origin", REPO_URL],
            cwd=cwd, capture_output=True, text=True,
        )


def _check_git_updates() -> tuple[bool, str]:
    """Fetch from origin and check if there are new commits.

    Returns:
        (has_updates, summary) where summary is the commit log or a status message.
    """
    project_root = _get_project_root()
    cwd = str(project_root)

    _ensure_origin(cwd)

    result = subprocess.run(
        ["git", "fetch", "origin", "main"],
        cwd=cwd, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False, f"git fetch failed: {result.stderr.strip()}"

    result = subprocess.run(
        ["git", "log", "HEAD..origin/main", "--oneline"],
        cwd=cwd, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False, f"git log failed: {result.stderr.strip()}"

    commits = result.stdout.strip()
    if not commits:
        return False, "Already up to date."

    count = len(commits.splitlines())
    return True, f"{count} new commit(s):\n{commits}"


def _check_pip_updates() -> tuple[bool, str]:
    """Check PyPI for a newer version of nvidia-driver-setup.

    Returns:
        (has_updates, summary)
    """
    from . import __version__ as current_version

    result = subprocess.run(
        [sys.executable, "-m", "pip", "index", "versions", "nvidia-driver-setup"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False, f"pip index failed: {result.stderr.strip()}"

    # Output format: "nvidia-driver-setup (X.Y.Z)"
    output = result.stdout.strip()
    for line in output.splitlines():
        if "nvidia-driver-setup" in line and "(" in line:
            latest = line.split("(")[1].split(")")[0].strip()
            if latest != current_version:
                return True, f"Current: {current_version} -> Available: {latest}"
            return False, f"Already at latest version ({current_version})."

    return False, "Could not determine latest version."


def _perform_git_update() -> bool:
    """Pull latest changes and reinstall in editable mode.

    Returns:
        True on success.
    """
    project_root = _get_project_root()
    cwd = str(project_root)

    log_info("Pulling latest changes...")
    result = subprocess.run(
        ["git", "pull", "origin", "main"],
        cwd=cwd, capture_output=True, text=True,
    )
    if result.returncode != 0:
        log_error(f"git pull failed: {result.stderr.strip()}")
        return False
    log_info(result.stdout.strip())

    log_info("Reinstalling package...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", "."],
        cwd=cwd, capture_output=True, text=True,
    )
    if result.returncode != 0:
        log_error(f"pip install failed: {result.stderr.strip()}")
        return False

    return True


def _perform_pip_update() -> bool:
    """Upgrade nvidia-driver-setup from PyPI.

    Returns:
        True on success.
    """
    log_info("Upgrading from PyPI...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "nvidia-driver-setup"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        log_error(f"pip upgrade failed: {result.stderr.strip()}")
        return False

    return True


def run_self_update() -> None:
    """Public entry point: detect method, check for updates, confirm, update."""
    log_step("Self-Update Check")

    method = detect_install_method()
    log_info(f"Install method: {method.value}")

    if method == InstallMethod.GIT_CLONE:
        has_updates, summary = _check_git_updates()
    elif method == InstallMethod.PIP:
        has_updates, summary = _check_pip_updates()
    else:
        log_warn("Cannot determine install method. Update manually.")
        return

    log_info(summary)

    if not has_updates:
        return

    if not prompt_yes_no("Apply update?"):
        log_info("Update skipped.")
        return

    if method == InstallMethod.GIT_CLONE:
        success = _perform_git_update()
    else:
        success = _perform_pip_update()

    if success:
        log_success("Update applied! Please restart nvidia-setup for changes to take effect.")
    else:
        log_error("Update failed. See errors above.")

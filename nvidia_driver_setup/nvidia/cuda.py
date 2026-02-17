"""CUDA version management.

Discovers available CUDA container image versions from Docker Hub,
with offline fallback to configs/cuda_versions.json.
"""

import json
import os
import re
import urllib.request
from typing import Optional

from ..utils.logging import log_info, log_warn, log_step
from ..utils.prompts import prompt_choice, prompt_input

# Docker Hub API for nvidia/cuda tags, filtered to one variant to keep it fast.
_DOCKERHUB_TAGS_URL = (
    "https://hub.docker.com/v2/repositories/nvidia/cuda/tags/"
    "?page_size=100&name=devel-ubuntu22.04"
)
_DOCKERHUB_TIMEOUT = 15  # seconds

# Minimum Linux driver required per CUDA version (from NVIDIA release notes).
# Keys are the CUDA *image* version (X.Y.Z); values are the min driver string.
_MIN_DRIVER: dict[str, str] = {
    "13.1.1": "590.48.01",
    "13.1.0": "590.44.01",
    "13.0.2": "580.95.05",
    "13.0.1": "580.82.07",
    "13.0.0": "580.65.06",
    "12.9.1": "575.57.08",
    "12.9.0": "575.51.03",
    "12.8.1": "570.124.06",
    "12.8.0": "570.26",
    "12.6.3": "560.35.05",
    "12.6.2": "560.35.03",
    "12.6.1": "560.35.03",
    "12.6.0": "560.28.03",
    "12.5.1": "555.42.06",
    "12.5.0": "555.42.02",
    "12.4.1": "550.54.15",
    "12.4.0": "550.54.14",
    "12.3.2": "545.23.08",
    "12.3.1": "545.23.08",
    "12.3.0": "545.23.06",
    "12.2.2": "535.104.05",
    "12.2.0": "535.54.03",
    "12.1.1": "530.30.02",
    "12.1.0": "530.30.02",
    "12.0.1": "525.85.12",
    "12.0.0": "525.60.13",
    "11.8.0": "520.61.05",
    "11.7.1": "515.48.07",
}


def _fetch_versions_from_dockerhub() -> Optional[list[str]]:
    """Fetch available CUDA versions from Docker Hub nvidia/cuda tags.

    Returns:
        Sorted list of version strings (newest first), or None on failure.
    """
    versions: set[str] = set()
    url: Optional[str] = _DOCKERHUB_TAGS_URL

    try:
        while url:
            req = urllib.request.Request(
                url, headers={"User-Agent": "nvidia-docker-setup/1.0"}
            )
            resp = urllib.request.urlopen(req, timeout=_DOCKERHUB_TIMEOUT)
            data = json.loads(resp.read())

            for tag in data.get("results", []):
                match = re.match(r"^(\d+\.\d+\.\d+)", tag["name"])
                if match:
                    versions.add(match.group(1))

            url = data.get("next")

        if not versions:
            return None

        return sorted(
            versions,
            key=lambda v: [int(x) for x in v.split(".")],
            reverse=True,
        )
    except Exception as exc:
        log_warn(f"Could not fetch versions from Docker Hub: {exc}")
        return None


def _load_fallback_versions() -> dict[str, str]:
    """Load CUDA versions from the local configs/cuda_versions.json fallback."""
    config_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..", "configs", "cuda_versions.json",
    )

    try:
        with open(config_path, "r") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {
            "12.8.0": "Recent stable - Broad GPU support",
            "12.6.0": "Stable release - Good compatibility",
            "12.4.0": "Stable release - RTX 40 series optimized",
            "11.8.0": "Legacy support - Mature and stable",
        }


def _classify_version(version: str) -> str:
    """Return a short description tag based on the major.minor family."""
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


def select_cuda_version() -> str:
    """Select CUDA version for installation."""
    log_step("CUDA Version Selection")

    log_info("This selection determines which CUDA version will be used in Docker containers.")
    log_info("It does not install CUDA on the host - that's handled by the NVIDIA driver.\n")
    log_info("Fetching available versions from Docker Hub...")

    live_versions = _fetch_versions_from_dockerhub()

    if live_versions:
        log_info(f"Found {len(live_versions)} available CUDA image versions.")
        choices: list[str] = []
        version_list: list[str] = []

        for version in live_versions:
            tag = _classify_version(version)
            min_drv = _MIN_DRIVER.get(version)
            driver_note = f"  (min driver: {min_drv})" if min_drv else ""
            choices.append(f"{version} - {tag}{driver_note}")
            version_list.append(version)
    else:
        log_warn("Falling back to offline version list.")
        fallback = _load_fallback_versions()
        choices = []
        version_list = []
        for version, description in fallback.items():
            min_drv = _MIN_DRIVER.get(version)
            driver_note = f"  (min driver: {min_drv})" if min_drv else ""
            choices.append(f"{version} - {description}{driver_note}")
            version_list.append(version)

    choices.append("Enter custom version")

    # Display the menu
    print("\nAvailable CUDA versions for containers:")
    for i, choice in enumerate(choices, 1):
        default_marker = " (recommended)" if i == 1 else ""
        print(f"  {i}. {choice}{default_marker}")

    print()

    # Get user selection
    choice_idx = prompt_choice(
        "Select CUDA version",
        [f"Option {i}" for i in range(1, len(choices) + 1)],
        default=0,
    )

    if choice_idx == len(choices) - 1:  # Custom version option
        cuda_version = prompt_input("Enter CUDA version (e.g., 12.4.0)")
        if not cuda_version:
            log_info("No version entered, using default 12.8.0")
            cuda_version = "12.8.0"
    else:
        cuda_version = version_list[choice_idx]

    log_info(f"Selected CUDA version: {cuda_version}")

    # Show min driver requirement
    min_drv = _MIN_DRIVER.get(cuda_version)
    if min_drv:
        log_info(f"Minimum driver required: {min_drv}")
    else:
        log_info("Minimum driver: check NVIDIA documentation for this version")

    return cuda_version

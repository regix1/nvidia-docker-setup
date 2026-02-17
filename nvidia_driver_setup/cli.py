"""NVIDIA Driver Setup - Command Line Interface

Entry point for the nvidia-setup CLI command and python3 -m nvidia_driver_setup.
"""

import os
import sys
import traceback

from nvidia_driver_setup.utils.logging import log_error, log_step, log_info, log_success
from nvidia_driver_setup.utils.prompts import prompt_yes_no, prompt_multi_select
from nvidia_driver_setup.system.checks import (
    run_preliminary_checks,
    detect_existing_installations,
    get_system_info,
    display_system_info,
)
from nvidia_driver_setup.utils.system import full_nvidia_cleanup, cleanup_nvidia_repos
from nvidia_driver_setup.nvidia.drivers import select_nvidia_driver
from nvidia_driver_setup.nvidia.cuda import select_cuda_version
from nvidia_driver_setup.docker.setup import setup_docker
from nvidia_driver_setup.nvidia.patches import apply_nvidia_patches, get_nvenc_session_info
from nvidia_driver_setup.docker.config import configure_docker_for_media

# Execution priority per menu index (lower = runs first).
# Self-update always runs last.
EXECUTION_ORDER: dict[int, int] = {
    0: 1,  # NVIDIA Drivers
    1: 2,  # Docker
    2: 3,  # CUDA
    3: 4,  # Patches
    4: 5,  # Media Config
    5: 6,  # System Audit / Cleanup
    6: 7,  # Self-Update (always last)
}

# Menu indices whose execution can change installed component state.
# Only re-run detect_existing_installations() when these ran.
_STATUS_CHANGING_INDICES: set[int] = {0, 1, 3, 4}  # drivers, docker, patches, media


def show_banner() -> None:
    """Display application banner."""
    banner = """
\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557
\u2551               NVIDIA Driver Setup - Python                  \u2551
\u2551          Hardware Acceleration for Media Servers            \u2551
\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d
"""
    print(banner)


def _check_nvenc_patch_status() -> str:
    """Return a short status label for the NVENC patch state.

    Uses get_nvenc_session_info() for smart detection that accounts
    for professional GPUs, driver version, and patch state.
    """
    try:
        info = get_nvenc_session_info()
        return info['status_label']
    except Exception:
        return ""


def _check_media_config_status() -> str:
    """Check if Docker is configured for media servers.

    Returns:
        Status string: '[OK]' or '[--]'
    """
    try:
        daemon_config = "/etc/docker/daemon.json"
        if os.path.exists(daemon_config):
            with open(daemon_config, "r") as fh:
                content = fh.read()
                if "nvidia" in content.lower():
                    return "[OK]"
    except Exception:
        pass
    return "[--]"


def build_menu_options(
    installations: dict,
) -> tuple[list[str], list[str], list[str]]:
    """Build the multi-select menu items from current installation state.

    Returns:
        (options, descriptions, statuses) - parallel lists for prompt_multi_select.
    """
    options: list[str] = []
    descriptions: list[str] = []
    statuses: list[str] = []

    # 0 - NVIDIA Drivers
    if installations["nvidia_driver"]["installed"]:
        options.append(f"Reinstall NVIDIA Drivers (Current: {installations['nvidia_driver']['version']})")
        descriptions.append("Reinstall or update NVIDIA drivers")
        statuses.append("[OK]")
    else:
        options.append("Install NVIDIA Drivers")
        descriptions.append("Install NVIDIA GPU drivers")
        statuses.append("[--]")

    # 1 - Docker
    if installations["docker"]["installed"]:
        options.append(f"Reconfigure Docker (Current: {installations['docker']['version']})")
        descriptions.append("Reconfigure Docker with NVIDIA support")
        statuses.append("[OK]")
    else:
        options.append("Install Docker with NVIDIA Support")
        descriptions.append("Install Docker and NVIDIA Container Toolkit")
        statuses.append("[--]")

    # 2 - CUDA
    options.append("Select CUDA Version")
    descriptions.append("Choose CUDA version for containers")
    statuses.append("")

    # 3 - Patches
    nvenc_status = _check_nvenc_patch_status()
    options.append("Apply NVIDIA Patches (NVENC/NvFBC)")
    descriptions.append("Remove NVENC session limits and enable NvFBC")
    statuses.append(nvenc_status)

    # 4 - Media Config
    media_status = _check_media_config_status()
    options.append("Configure for Media Servers")
    descriptions.append("Optimize Docker for Plex/media processing")
    statuses.append(media_status)

    # 5 - System Audit / Cleanup
    options.append("System Audit / Cleanup")
    descriptions.append("Scan for old drivers, stale libraries, and repo issues")
    statuses.append("")

    # 6 - Self-Update
    options.append("Update nvidia-setup")
    descriptions.append("Check for and apply updates to this tool")
    statuses.append("")

    return options, descriptions, statuses


def _execute_single_item(idx: int, installations: dict) -> None:
    """Dispatch a single menu item by its 0-based index."""
    if idx == 0:  # NVIDIA Drivers
        if installations["nvidia_driver"]["installed"]:
            if prompt_yes_no(
                f"NVIDIA driver {installations['nvidia_driver']['version']} is installed. Reinstall?"
            ):
                select_nvidia_driver()
        else:
            select_nvidia_driver()

    elif idx == 1:  # Docker
        if installations["docker"]["installed"]:
            if prompt_yes_no(
                f"Docker {installations['docker']['version']} is installed. Reconfigure?"
            ):
                setup_docker()
        else:
            setup_docker()

    elif idx == 2:  # CUDA
        select_cuda_version()

    elif idx == 3:  # Patches
        apply_nvidia_patches()

    elif idx == 4:  # Media Config
        configure_docker_for_media()

    elif idx == 5:  # System Audit / Cleanup
        log_step("System Audit / Cleanup")
        log_info("Scanning for issues (dry-run)...")
        has_issues = full_nvidia_cleanup(dry_run=True)
        if has_issues:
            if prompt_yes_no("Issues found. Apply fixes now?"):
                full_nvidia_cleanup(dry_run=False)
                cleanup_nvidia_repos()
        else:
            log_success("System is clean -- no old drivers or stale libraries found")
            cleanup_nvidia_repos()

    elif idx == 6:  # Self-Update
        from nvidia_driver_setup.updater import run_self_update
        run_self_update()


def execute_selected_items(selected: list[int], installations: dict) -> None:
    """Execute selected menu items in the correct order.

    Items are sorted by EXECUTION_ORDER so that drivers install before
    Docker, patches come after CUDA, and self-update always runs last.
    """
    ordered = sorted(selected, key=lambda idx: EXECUTION_ORDER.get(idx, 99))
    total = len(ordered)
    for step, idx in enumerate(ordered, 1):
        log_step(f"[{step}/{total}] Running: item {idx + 1}")
        _execute_single_item(idx, installations)


def show_post_installation_summary() -> None:
    """Show post-installation summary and next steps."""
    log_success("Installation completed successfully!")

    summary = """
======================================================================
                       Installation Summary
======================================================================

Next Steps:
1. Reboot your system for all changes to take effect

2. Test NVIDIA Docker integration:
   docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi

3. For Plex with GPU acceleration:
   - Copy template: cp templates/plex-nvidia.yml /opt/docker-templates/
   - Edit paths and claim token
   - Start: docker-compose -f /opt/docker-templates/plex-nvidia.yml up -d

4. Performance optimization (recommended):
   - Add kernel parameters: pcie_port_pm=off pcie_aspm.policy=performance
   - Edit /etc/default/grub and run update-grub
======================================================================
"""

    print(summary)


def _display_status(installations: dict) -> None:
    """Print a compact installation-status block."""
    nvidia_status = (
        f"[OK] {installations['nvidia_driver']['version']}"
        if installations["nvidia_driver"]["installed"]
        else "[--] Not installed"
    )
    docker_status = (
        f"[OK] {installations['docker']['version']}"
        if installations["docker"]["installed"]
        else "[--] Not installed"
    )
    runtime_status = (
        "[OK] Available"
        if installations["nvidia_runtime"]["installed"]
        else "[--] Not configured"
    )
    print("\nInstallation Status:")
    print(f"  NVIDIA Driver:  {nvidia_status}")
    print(f"  Docker:         {docker_status}")
    print(f"  NVIDIA Runtime: {runtime_status}")
    print()


def main() -> None:
    """Main installation process."""
    try:
        # Check if running as root
        if os.geteuid() != 0:
            log_error("This script must be run as root (sudo).")
            sys.exit(1)

        show_banner()

        # Gather and display system information first
        log_step("Gathering System Information")
        system_info = get_system_info()
        display_system_info(system_info)

        # Run system checks (fast: GPU, OS, deps, internet)
        run_preliminary_checks()

        # Detect existing installations
        log_step("Detecting Installed Components")
        installations = detect_existing_installations()

        any_actions_ran = False

        # Interactive multi-select menu loop
        while True:
            _display_status(installations)

            options, descriptions, statuses = build_menu_options(installations)

            selected = prompt_multi_select(
                prompt="NVIDIA Driver Setup",
                options=options,
                descriptions=descriptions,
                statuses=statuses,
            )

            if not selected:
                break

            execute_selected_items(selected, installations)
            any_actions_ran = True

            # Only refresh detection if status-changing items ran
            if _STATUS_CHANGING_INDICES.intersection(selected):
                installations = detect_existing_installations()

            # Pause so user can read output before menu redraws
            print()
            log_info("Press Enter to return to menu...")
            input()

            # Clear screen for fresh menu redraw
            print("\033[2J\033[H", end="", flush=True)
            show_banner()

        if any_actions_ran:
            show_post_installation_summary()

            if prompt_yes_no("Would you like to reboot now?"):
                os.system("reboot")
        else:
            log_info("No changes made. Goodbye!")

    except KeyboardInterrupt:
        print()
        log_info("Cancelled.")
        sys.exit(1)
    except Exception as e:
        log_error(f"Installation failed: {str(e)}")
        log_error(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()

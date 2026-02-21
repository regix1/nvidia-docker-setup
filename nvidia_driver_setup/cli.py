"""GPU Driver Setup - Command Line Interface

Entry point for the nvidia-setup CLI command and python3 -m nvidia_driver_setup.
Supports NVIDIA, Intel, and AMD GPUs with vendor-appropriate menu items.
"""

import os
import sys
import traceback

from nvidia_driver_setup.utils.logging import log_error, log_step, log_info, log_success
from nvidia_driver_setup.utils.prompts import prompt_yes_no, prompt_multi_select
from nvidia_driver_setup.utils.system import full_nvidia_cleanup, cleanup_nvidia_repos, detect_gpu_vendors
from nvidia_driver_setup.system.checks import (
    run_preliminary_checks,
    detect_existing_installations,
    get_system_info,
    display_system_info,
)
from nvidia_driver_setup.nvidia.drivers import select_nvidia_driver
from nvidia_driver_setup.nvidia.cuda import select_cuda_version
from nvidia_driver_setup.nvidia.vulkan import install_vulkan_sdk
from nvidia_driver_setup.nvidia.cuda_toolkit import install_cuda_toolkit
from nvidia_driver_setup.docker.setup import setup_docker
from nvidia_driver_setup.nvidia.patches import apply_nvidia_patches, get_nvenc_session_info
from nvidia_driver_setup.docker.config import configure_docker_for_media


# ---------------------------------------------------------------------------
# Action identifiers (stable IDs independent of menu position)
# ---------------------------------------------------------------------------

ACTION_NVIDIA_DRIVERS = "nvidia_drivers"
ACTION_DOCKER = "docker"
ACTION_CUDA_VERSION = "cuda_version"
ACTION_VULKAN_SDK = "vulkan_sdk"
ACTION_CUDA_TOOLKIT = "cuda_toolkit"
ACTION_PATCHES = "patches"
ACTION_MEDIA_CONFIG = "media_config"
ACTION_SYSTEM_AUDIT = "system_audit"
ACTION_SELF_UPDATE = "self_update"

# Execution priority (lower = runs first).  Self-update always runs last.
EXECUTION_ORDER: dict[str, int] = {
    ACTION_NVIDIA_DRIVERS: 1,
    ACTION_DOCKER: 2,
    ACTION_CUDA_VERSION: 3,
    ACTION_VULKAN_SDK: 4,
    ACTION_CUDA_TOOLKIT: 5,
    ACTION_PATCHES: 6,
    ACTION_MEDIA_CONFIG: 7,
    ACTION_SYSTEM_AUDIT: 8,
    ACTION_SELF_UPDATE: 9,
}

# Actions whose execution can change installed component state.
_STATUS_CHANGING_ACTIONS: set[str] = {
    ACTION_NVIDIA_DRIVERS, ACTION_DOCKER, ACTION_VULKAN_SDK,
    ACTION_CUDA_TOOLKIT, ACTION_PATCHES, ACTION_MEDIA_CONFIG,
}


def show_banner() -> None:
    """Display application banner."""
    banner = """
\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557
\u2551               GPU Driver Setup - Python                      \u2551
\u2551          Hardware Acceleration for Media Servers            \u2551
\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d
"""
    print(banner)


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------

def _check_nvenc_patch_status() -> str:
    """Return a short status label for the NVENC patch state."""
    try:
        info = get_nvenc_session_info()
        return info['status_label']
    except Exception:
        return ""


def _check_media_config_status() -> str:
    """Check if Docker is configured for media servers."""
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


# ---------------------------------------------------------------------------
# Dynamic menu builder
# ---------------------------------------------------------------------------

def build_menu_options(
    installations: dict,
    gpu_vendors: list[str],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Build the multi-select menu items based on detected GPU vendors.

    NVIDIA-specific items (drivers, CUDA, patches) are only shown when an
    NVIDIA GPU is present.  Universal items (Docker, Vulkan SDK, media
    config, self-update) are always shown.

    Returns:
        (options, descriptions, statuses, action_ids) - parallel lists.
        ``action_ids`` maps each menu position back to an ACTION_* constant.
    """
    has_nvidia = "nvidia" in gpu_vendors

    options: list[str] = []
    descriptions: list[str] = []
    statuses: list[str] = []
    action_ids: list[str] = []

    # NVIDIA Drivers (NVIDIA only)
    if has_nvidia:
        if installations["nvidia_driver"]["installed"]:
            options.append(f"Reinstall NVIDIA Drivers (Current: {installations['nvidia_driver']['version']})")
            descriptions.append("Reinstall or update NVIDIA drivers")
            statuses.append("[OK]")
        else:
            options.append("Install NVIDIA Drivers")
            descriptions.append("Install NVIDIA GPU drivers")
            statuses.append("[--]")
        action_ids.append(ACTION_NVIDIA_DRIVERS)

    # Docker (universal)
    if installations["docker"]["installed"]:
        options.append(f"Reconfigure Docker (Current: {installations['docker']['version']})")
        descriptions.append("Reconfigure Docker with GPU support")
        statuses.append("[OK]")
    else:
        options.append("Install Docker with GPU Support")
        descriptions.append("Install Docker and configure GPU container runtime")
        statuses.append("[--]")
    action_ids.append(ACTION_DOCKER)

    # CUDA Container Version (NVIDIA only)
    if has_nvidia:
        options.append("Select CUDA Version")
        descriptions.append("Choose CUDA version for containers")
        statuses.append("")
        action_ids.append(ACTION_CUDA_VERSION)

    # Vulkan SDK (universal)
    if installations["vulkan_sdk"]["installed"]:
        options.append(f"Reinstall Vulkan SDK (Current: {installations['vulkan_sdk']['version']})")
        descriptions.append("Reinstall or update the LunarG Vulkan SDK")
        statuses.append("[OK]")
    else:
        options.append("Install Vulkan SDK")
        descriptions.append("LunarG Vulkan SDK (validation layers, SPIR-V tools, headers)")
        statuses.append("[--]")
    action_ids.append(ACTION_VULKAN_SDK)

    # CUDA Toolkit (NVIDIA only)
    if has_nvidia:
        if installations["cuda_toolkit"]["installed"]:
            options.append(f"Reinstall CUDA Toolkit (Current: {installations['cuda_toolkit']['version']})")
            descriptions.append("Reinstall or update the host CUDA Toolkit")
            statuses.append("[OK]")
        else:
            options.append("Install CUDA Toolkit")
            descriptions.append("NVIDIA CUDA Toolkit on host (nvcc, cuDNN, dev libraries)")
            statuses.append("[--]")
        action_ids.append(ACTION_CUDA_TOOLKIT)

    # NVIDIA Patches (NVIDIA only)
    if has_nvidia:
        nvenc_status = _check_nvenc_patch_status()
        options.append("Apply NVIDIA Patches (NVENC/NvFBC)")
        descriptions.append("Remove NVENC session limits and enable NvFBC")
        statuses.append(nvenc_status)
        action_ids.append(ACTION_PATCHES)

    # Media Config (universal)
    media_status = _check_media_config_status()
    options.append("Configure for Media Servers")
    descriptions.append("Optimize Docker for Plex/media processing")
    statuses.append(media_status)
    action_ids.append(ACTION_MEDIA_CONFIG)

    # System Audit / Cleanup (NVIDIA only — all cleanup logic is NVIDIA-specific)
    if has_nvidia:
        options.append("System Audit / Cleanup")
        descriptions.append("Scan for old drivers, stale libraries, and repo issues")
        statuses.append("")
        action_ids.append(ACTION_SYSTEM_AUDIT)

    # Self-Update (universal)
    options.append("Update nvidia-setup")
    descriptions.append("Check for and apply updates to this tool")
    statuses.append("")
    action_ids.append(ACTION_SELF_UPDATE)

    return options, descriptions, statuses, action_ids


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def _execute_action(action: str, installations: dict) -> None:
    """Dispatch a single menu action by its action ID."""
    if action == ACTION_NVIDIA_DRIVERS:
        if installations["nvidia_driver"]["installed"]:
            if prompt_yes_no(
                f"NVIDIA driver {installations['nvidia_driver']['version']} is installed. Reinstall?"
            ):
                select_nvidia_driver()
        else:
            select_nvidia_driver()

    elif action == ACTION_DOCKER:
        if installations["docker"]["installed"]:
            if prompt_yes_no(
                f"Docker {installations['docker']['version']} is installed. Reconfigure?"
            ):
                setup_docker()
        else:
            setup_docker()

    elif action == ACTION_CUDA_VERSION:
        select_cuda_version()

    elif action == ACTION_VULKAN_SDK:
        install_vulkan_sdk()

    elif action == ACTION_CUDA_TOOLKIT:
        install_cuda_toolkit()

    elif action == ACTION_PATCHES:
        apply_nvidia_patches()

    elif action == ACTION_MEDIA_CONFIG:
        configure_docker_for_media()

    elif action == ACTION_SYSTEM_AUDIT:
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

    elif action == ACTION_SELF_UPDATE:
        from nvidia_driver_setup.updater import run_self_update
        run_self_update()


def execute_selected_items(
    selected: list[int],
    action_ids: list[str],
    installations: dict,
) -> None:
    """Execute selected menu items in the correct order.

    Items are sorted by EXECUTION_ORDER so that drivers install before
    Docker, patches come after CUDA, and self-update always runs last.
    """
    actions = [action_ids[i] for i in selected]
    ordered = sorted(actions, key=lambda a: EXECUTION_ORDER.get(a, 99))
    total = len(ordered)
    for step, action in enumerate(ordered, 1):
        log_step(f"[{step}/{total}] Running: {action}")
        _execute_action(action, installations)


# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------

def _display_status(installations: dict, gpu_vendors: list[str]) -> None:
    """Print a compact installation-status block."""
    has_nvidia = "nvidia" in gpu_vendors

    docker_status = (
        f"[OK] {installations['docker']['version']}"
        if installations["docker"]["installed"]
        else "[--] Not installed"
    )
    vulkan_sdk_status = (
        f"[OK] {installations['vulkan_sdk']['version']}"
        if installations["vulkan_sdk"]["installed"]
        else "[--] Not installed"
    )

    print("\nInstallation Status:")

    if has_nvidia:
        nvidia_status = (
            f"[OK] {installations['nvidia_driver']['version']}"
            if installations["nvidia_driver"]["installed"]
            else "[--] Not installed"
        )
        runtime_status = (
            "[OK] Available"
            if installations["nvidia_runtime"]["installed"]
            else "[--] Not configured"
        )
        cuda_toolkit_status = (
            f"[OK] {installations['cuda_toolkit']['version']}"
            if installations["cuda_toolkit"]["installed"]
            else "[--] Not installed"
        )
        print(f"  NVIDIA Driver:  {nvidia_status}")
        print(f"  NVIDIA Runtime: {runtime_status}")
        print(f"  CUDA Toolkit:   {cuda_toolkit_status}")

    print(f"  Docker:         {docker_status}")
    print(f"  Vulkan SDK:     {vulkan_sdk_status}")

    vendor_label = ", ".join(v.upper() for v in gpu_vendors) if gpu_vendors else "None detected"
    print(f"  GPU Vendors:    {vendor_label}")
    print()


# ---------------------------------------------------------------------------
# Post-install summary
# ---------------------------------------------------------------------------

def show_post_installation_summary(gpu_vendors: list[str]) -> None:
    """Show post-installation summary and next steps."""
    log_success("Installation completed successfully!")

    print("\n" + "=" * 70)
    print("                       Installation Summary")
    print("=" * 70)
    print("\nNext Steps:")
    print("1. Reboot your system for all changes to take effect")

    if "nvidia" in gpu_vendors:
        print("\n2. Test NVIDIA Docker integration:")
        print("   docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi")
        print("\n3. For Plex with GPU acceleration:")
        print("   - Copy template: cp templates/plex-nvidia.yml /opt/docker-templates/")
        print("   - Edit paths and claim token")
        print("   - Start: docker-compose -f /opt/docker-templates/plex-nvidia.yml up -d")

    if "intel" in gpu_vendors:
        print("\n   For Intel QSV in Docker containers:")
        print("   - Pass the render device: --device /dev/dri:/dev/dri")
        print("   - Verify with: vainfo (inside container)")

    print("\n4. Performance optimization (recommended):")
    print("   - Add kernel parameters: pcie_port_pm=off pcie_aspm.policy=performance")
    print("   - Edit /etc/default/grub and run update-grub")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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

        # Detect GPU vendors and existing installations
        gpu_vendors = detect_gpu_vendors()
        log_step("Detecting Installed Components")
        installations = detect_existing_installations()

        any_actions_ran = False

        # Interactive multi-select menu loop
        while True:
            _display_status(installations, gpu_vendors)

            options, descriptions, statuses, action_ids = build_menu_options(
                installations, gpu_vendors,
            )

            selected = prompt_multi_select(
                prompt="GPU Driver Setup",
                options=options,
                descriptions=descriptions,
                statuses=statuses,
            )

            if not selected:
                break

            execute_selected_items(selected, action_ids, installations)
            any_actions_ran = True

            # Only refresh detection if status-changing items ran
            selected_actions = {action_ids[i] for i in selected}
            if _STATUS_CHANGING_ACTIONS.intersection(selected_actions):
                installations = detect_existing_installations()

            # Pause so user can read output before menu redraws
            print()
            log_info("Press Enter to return to menu...")
            input()

            # Clear screen for fresh menu redraw
            print("\033[2J\033[H", end="", flush=True)
            show_banner()

        if any_actions_ran:
            show_post_installation_summary(gpu_vendors)

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

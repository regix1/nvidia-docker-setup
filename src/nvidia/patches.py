"""NVIDIA driver patches for NVENC and NvFBC"""

import tempfile
import os
from utils.logging import log_info, log_step, log_warn, log_success
from utils.prompts import prompt_yes_no
from utils.system import run_command


SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'scripts'
)


def apply_nvidia_patches():
    """Apply NVIDIA patches for unlimited NVENC sessions"""
    log_step("NVIDIA NVENC & NvFBC unlimited sessions patch...")

    if not prompt_yes_no("Would you like to patch NVIDIA drivers to remove NVENC session limit?"):
        return

    _apply_nvenc_patch()

    if prompt_yes_no("Would you also like to patch for NvFBC support (useful for OBS)?"):
        _apply_nvfbc_patch()


def _apply_nvenc_patch():
    """Apply NVENC session limit patch using our binary patcher.

    Uses Python3-based anchor scanning to precisely locate and patch the
    session-limit check in libnvidia-encode.so.  Automatically detects
    the byte-pattern variant for the installed driver version.
    """
    script_path = os.path.join(SCRIPTS_DIR, 'nvenc-patch.sh')

    if os.path.isfile(script_path):
        log_info("Applying NVENC session limit patch...")
        try:
            run_command(f"chmod +x {script_path}")
            run_command(f"bash {script_path} -v")
            log_success("NVENC session limit patch applied!")
            return
        except Exception as e:
            log_warn(f"Custom patch script failed: {e}")
            log_info("Trying upstream keylase/nvidia-patch as fallback...")

    # Fallback: upstream keylase/nvidia-patch
    _apply_upstream_script("patch.sh", "NVENC")


def _apply_nvfbc_patch():
    """Apply NvFBC patch for OBS / screen-capture support"""
    _apply_upstream_script("patch-fbc.sh", "NvFBC")


def _apply_upstream_script(script_name: str, label: str):
    """Clone keylase/nvidia-patch and run the given script"""
    log_info(f"Applying {label} patch via upstream keylase/nvidia-patch...")

    with tempfile.TemporaryDirectory() as tmp:
        original_dir = os.getcwd()
        try:
            os.chdir(tmp)
            run_command("git clone https://github.com/keylase/nvidia-patch.git .")
            run_command(f"chmod +x {script_name}")
            run_command(f"bash ./{script_name}")
            log_success(f"{label} patch applied!")
        except Exception as e:
            log_warn(f"{label} patching failed: {e}")
            log_warn("You can manually apply the patch later if needed")
        finally:
            os.chdir(original_dir)



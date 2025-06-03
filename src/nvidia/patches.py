"""NVIDIA driver patches for NVENC and NvFBC"""

import tempfile
import os
from utils.logging import log_info, log_step, log_warn
from utils.prompts import prompt_yes_no
from utils.system import run_command


def apply_nvidia_patches():
    """Apply NVIDIA patches for unlimited sessions"""
    log_step("NVIDIA NVENC & NvFBC unlimited sessions patch...")
    
    if not prompt_yes_no("Would you like to patch NVIDIA drivers to remove NVENC session limit?"):
        return
    
    with tempfile.TemporaryDirectory() as temp_dir:
        original_dir = os.getcwd()
        
        try:
            os.chdir(temp_dir)
            _download_nvidia_patcher()
            _apply_nvenc_patch()
            
            if prompt_yes_no("Would you also like to patch for NvFBC support (useful for OBS)?"):
                _apply_nvfbc_patch()
                
            log_info("✓ NVIDIA driver successfully patched!")
            
        except Exception as e:
            log_warn(f"Patching failed: {e}")
            log_warn("You can manually apply patches later if needed")
        finally:
            os.chdir(original_dir)


def _download_nvidia_patcher():
    """Download the NVIDIA patcher from GitHub"""
    log_info("Downloading NVIDIA patcher...")
    
    run_command("git clone https://github.com/keylase/nvidia-patch.git .")


def _apply_nvenc_patch():
    """Apply NVENC session limit patch"""
    log_info("Applying NVENC session limit patch...")
    
    # Make the patch script executable
    run_command("chmod +x patch.sh")
    
    # Run the patch script
    run_command("bash ./patch.sh")


def _apply_nvfbc_patch():
    """Apply NvFBC patch for OBS support"""
    log_info("Applying NvFBC patch...")
    
    # Make the patch script executable
    run_command("chmod +x patch-fbc.sh")
    
    # Run the NvFBC patch script
    run_command("bash ./patch-fbc.sh")


def check_patch_status():
    """Check if patches have been applied"""
    log_info("Checking patch status...")
    
    try:
        # Check if patched files exist (this is a simplified check)
        nvidia_smi_output = run_command("nvidia-smi", capture_output=True, check=False)
        
        if nvidia_smi_output:
            log_info("NVIDIA driver is functional")
            # Additional patch verification could be added here
        else:
            log_warn("NVIDIA driver not responding")
            
    except Exception as e:
        log_warn(f"Could not verify patch status: {e}")


def show_patch_info():
    """Display information about available patches"""
    info = """
NVIDIA Patches Available:

1. NVENC Session Limit Patch:
   - Removes the 2-session limit for consumer GPUs
   - Allows unlimited simultaneous encoding sessions
   - Useful for multiple containers or applications

2. NvFBC Patch:
   - Enables NvFBC (NVIDIA Frame Buffer Capture)
   - Useful for OBS Studio and screen recording
   - Provides hardware-accelerated screen capture

Note: These patches modify NVIDIA driver files. While generally safe,
they may need to be reapplied after driver updates.
"""
    
    print(info)
"""CUDA version management"""

import json
import os
from utils.logging import log_info, log_step
from utils.prompts import prompt_choice, prompt_input


def select_cuda_version():
    """Select CUDA version for installation"""
    log_step("Selecting CUDA version...")
    
    cuda_versions = _load_cuda_versions()
    
    # Display available versions
    log_info("Available CUDA versions:")
    choices = []
    for i, (version, description) in enumerate(cuda_versions.items()):
        is_default = i == 0
        default_text = " (default)" if is_default else ""
        print(f"  {i+1}. {version}{default_text} - {description}")
        choices.append(version)
    
    choices.append("Other (enter manually)")
    
    # Get user selection
    choice_idx = prompt_choice(
        "Enter your choice or press Enter for default",
        choices,
        default=0
    )
    
    if choice_idx == len(choices) - 1:  # "Other" option
        cuda_version = prompt_input("Enter CUDA version manually")
    else:
        cuda_version = choices[choice_idx]
    
    log_info(f"Selected CUDA version: {cuda_version}")
    return cuda_version


def _load_cuda_versions():
    """Load CUDA versions from config file"""
    config_path = os.path.join(
        os.path.dirname(__file__), 
        '..', '..', 'configs', 'cuda_versions.json'
    )
    
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        # Fallback to hardcoded versions
        return {
            "12.4.0": "Latest stable release",
            "12.3.2": "Previous stable",
            "12.2.2": "LTS candidate",
            "12.1.1": "Stable release",
            "12.0.1": "Major version baseline",
            "11.8.0": "Legacy support",
            "11.7.1": "Legacy stable",
            "11.6.2": "Older legacy"
        }


def get_cuda_compatibility_info(cuda_version):
    """Get compatibility information for CUDA version"""
    compatibility_info = {
        "12.4.0": {
            "min_driver": "550.54.15",
            "features": ["Latest CUDA features", "RTX 40 series optimizations"]
        },
        "12.3.2": {
            "min_driver": "545.23.08", 
            "features": ["Stable performance", "Good compatibility"]
        },
        "11.8.0": {
            "min_driver": "520.61.05",
            "features": ["Mature release", "Wide compatibility"]
        }
    }
    
    return compatibility_info.get(cuda_version, {
        "min_driver": "Unknown",
        "features": ["Version-specific features"]
    })
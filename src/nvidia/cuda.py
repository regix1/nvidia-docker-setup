"""CUDA version management"""

import json
import os
from utils.logging import log_info, log_step
from utils.prompts import prompt_choice, prompt_input


def select_cuda_version():
    """Select CUDA version for installation"""
    log_step("CUDA Version Selection")
    
    cuda_versions = _load_cuda_versions()
    
    log_info("This selection determines which CUDA version will be used in Docker containers.")
    log_info("It does not install CUDA on the host - that's handled by the NVIDIA driver.\n")
    
    # Prepare choices for the menu
    choices = []
    for version, description in cuda_versions.items():
        choices.append(f"{version} - {description}")
    
    choices.append("Enter custom version")
    
    # Display the menu
    print("Available CUDA versions for containers:")
    for i, choice in enumerate(choices, 1):
        default_marker = " (recommended)" if i == 1 else ""
        print(f"  {i}. {choice}{default_marker}")
    
    print()
    
    # Get user selection
    choice_idx = prompt_choice(
        "Select CUDA version",
        [f"Option {i}" for i in range(1, len(choices) + 1)],
        default=0
    )
    
    if choice_idx == len(choices) - 1:  # Custom version option
        cuda_version = prompt_input("Enter CUDA version (e.g., 12.4.0)")
        if not cuda_version:
            log_info("No version entered, using default 12.4.0")
            cuda_version = "12.4.0"
    else:
        # Extract version from the selected choice
        cuda_version = list(cuda_versions.keys())[choice_idx]
    
    log_info(f"Selected CUDA version: {cuda_version}")
    
    # Show compatibility info if available
    compat_info = get_cuda_compatibility_info(cuda_version)
    if compat_info.get('min_driver'):
        log_info(f"Minimum driver required: {compat_info['min_driver']}")
    
    if compat_info.get('features'):
        log_info("Key features:")
        for feature in compat_info['features']:
            log_info(f"  • {feature}")
    
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
            "12.4.0": "Latest stable release - RTX 40 series optimized",
            "12.3.2": "Previous stable - Wide compatibility", 
            "12.2.2": "LTS candidate - Enterprise ready",
            "12.1.1": "Stable release - Good performance",
            "12.0.1": "Major version baseline - Reliable",
            "11.8.0": "Legacy support - Mature and stable",
            "11.7.1": "Legacy stable - Proven compatibility",
            "11.6.2": "Older legacy - Basic support"
        }


def get_cuda_compatibility_info(cuda_version):
    """Get compatibility information for CUDA version"""
    compatibility_info = {
        "13.0.0": {
            "min_driver": "570.86.15",
            "features": ["Latest CUDA architecture", "RTX 50 series support", "Enhanced AI/ML performance"]
        },
        "12.8.0": {
            "min_driver": "570.86.15",
            "features": ["Recent CUDA features", "Broad GPU support", "Stable performance"]
        },
        "12.6.0": {
            "min_driver": "560.28.03",
            "features": ["Mature release", "Good compatibility", "Stable performance"]
        },
        "12.4.0": {
            "min_driver": "550.54.15",
            "features": ["Latest CUDA features", "RTX 40 series optimizations", "Advanced AI/ML support"]
        },
        "12.3.2": {
            "min_driver": "545.23.08", 
            "features": ["Stable performance", "Good compatibility", "Mature ecosystem"]
        },
        "12.2.2": {
            "min_driver": "535.86.10",
            "features": ["LTS candidate", "Enterprise ready", "Long-term support"]
        },
        "11.8.0": {
            "min_driver": "520.61.05",
            "features": ["Mature release", "Wide compatibility", "Proven stability"]
        },
        "11.7.1": {
            "min_driver": "515.43.04",
            "features": ["Legacy stable", "Broad hardware support", "Well-tested"]
        }
    }
    
    return compatibility_info.get(cuda_version, {
        "min_driver": "Check NVIDIA documentation",
        "features": ["Version-specific features available"]
    })



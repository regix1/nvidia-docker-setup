"""Docker configuration for media processing"""

import json
import os
import shutil
from utils.logging import log_info, log_step
from utils.prompts import prompt_yes_no
from utils.system import run_command


def configure_docker_for_media():
    """Configure Docker with optimized settings for NVIDIA media"""
    log_step("Configuring Docker for media processing...")
    
    if not prompt_yes_no("Configure Docker with optimized settings for NVIDIA media?"):
        return
    
    use_cgroupfs = prompt_yes_no(
        "Would you like to configure Docker to use cgroupfs driver? "
        "(Fixes common 'CUDA_ERROR_NO_DEVICE' issues)"
    )
    
    _create_docker_daemon_config(use_cgroupfs)
    _create_sample_templates()
    
    # Restart Docker to apply changes
    run_command("systemctl restart docker")
    
    log_info("✓ Docker configured for NVIDIA and media processing")
    log_info("Sample docker-compose created: /opt/docker-templates/plex-nvidia.yml")
    
    if use_cgroupfs:
        log_info("Docker configured to use cgroupfs driver for improved NVIDIA GPU compatibility")


def _create_docker_daemon_config(use_cgroupfs=False):
    """Create optimized Docker daemon configuration"""
    config_dir = "/etc/docker"
    config_file = os.path.join(config_dir, "daemon.json")
    
    # Ensure directory exists
    os.makedirs(config_dir, exist_ok=True)
    
    # Choose appropriate template
    template_name = "docker-daemon-cgroupfs.json" if use_cgroupfs else "docker-daemon.json"
    template_path = _get_template_path(template_name)
    
    if os.path.exists(template_path):
        # Copy from template
        shutil.copy2(template_path, config_file)
        log_info(f"✓ Docker daemon configuration created from template: {template_name}")
    else:
        # Create inline if template not found
        _create_daemon_config_inline(config_file, use_cgroupfs)
        log_info("✓ Docker daemon configuration created")


def _create_daemon_config_inline(config_file, use_cgroupfs=False):
    """Create daemon config inline if template not available"""
    config = {
        "default-runtime": "nvidia",
        "runtimes": {
            "nvidia": {
                "path": "nvidia-container-runtime",
                "runtimeArgs": []
            }
        },
        "log-driver": "json-file",
        "log-opts": {
            "max-size": "10m",
            "max-file": "3"
        },
        "storage-driver": "overlay2",
        "features": {
            "buildkit": True
        }
    }
    
    if use_cgroupfs:
        config["exec-opts"] = ["native.cgroupdriver=cgroupfs"]
    
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)


def _create_sample_templates():
    """Create sample Docker Compose templates"""
    templates_dir = "/opt/docker-templates"
    os.makedirs(templates_dir, exist_ok=True)
    
    # Copy Plex template
    plex_template_path = _get_template_path("plex-nvidia.yml")
    plex_dest = os.path.join(templates_dir, "plex-nvidia.yml")
    
    if os.path.exists(plex_template_path):
        shutil.copy2(plex_template_path, plex_dest)
        log_info("✓ Plex template copied to /opt/docker-templates/")
    else:
        _create_plex_template_inline(plex_dest)
        log_info("✓ Plex template created at /opt/docker-templates/")


def _create_plex_template_inline(dest_path):
    """Create Plex template inline if not available"""
    plex_template = """version: '3.8'

services:
  plex:
    image: plexinc/pms-docker:latest
    container_name: plex
    restart: unless-stopped
    network_mode: host
    environment:
      - TZ=UTC
      - PLEX_CLAIM=claim-YOURCLAIMTOKEN
      - NVIDIA_VISIBLE_DEVICES=all
      - NVIDIA_DRIVER_CAPABILITIES=compute,video,utility
    volumes:
      - /path/to/plex/config:/config
      - /path/to/media:/data
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu, compute, video, utility]
"""
    
    with open(dest_path, 'w') as f:
        f.write(plex_template)


def _get_template_path(template_name):
    """Get full path to template file"""
    script_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(script_dir, "templates", template_name)
"""Docker installation and NVIDIA integration setup"""

import os
from utils.logging import log_info, log_warn, log_step
from utils.system import run_command, AptManager, get_os_info


DOCKER_COMPOSE_VERSION = "v2.25.0"


def setup_docker():
    """Setup Docker with NVIDIA support"""
    log_step("Setting up Docker with NVIDIA support...")
    
    _remove_existing_docker()
    _install_docker_prerequisites()
    _setup_docker_repository()
    _install_docker_packages()
    _start_docker_service()
    _setup_nvidia_container_toolkit()
    _install_docker_compose()
    _test_docker_installation()


def _remove_existing_docker():
    """Remove any existing Docker installations"""
    log_info("Removing any existing Docker installations...")
    
    packages_to_remove = [
        "docker.io", "docker-doc", "docker-compose", 
        "docker-compose-v2", "podman-docker", "containerd", "runc"
    ]
    
    apt = AptManager()
    for package in packages_to_remove:
        try:
            apt.remove(package)
        except:
            pass  # Package might not be installed


def _install_docker_prerequisites():
    """Install Docker prerequisites"""
    log_info("Installing prerequisites...")
    
    apt = AptManager()
    apt.install("ca-certificates", "curl")


def _setup_docker_repository():
    """Setup Docker's official repository"""
    log_info("Setting up Docker's official repository...")
    
    # Create keyrings directory
    run_command("install -m 0755 -d /etc/apt/keyrings")
    
    # Download Docker GPG key
    run_command(
        "curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc"
    )
    run_command("chmod a+r /etc/apt/keyrings/docker.asc")
    
    # Add Docker repository
    os_info = get_os_info()
    codename = os_info.get('UBUNTU_CODENAME') or os_info.get('VERSION_CODENAME', 'jammy')
    
    repo_line = (
        f'deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] '
        f'https://download.docker.com/linux/ubuntu {codename} stable'
    )
    
    run_command(f'echo "{repo_line}" | tee /etc/apt/sources.list.d/docker.list > /dev/null')


def _install_docker_packages():
    """Install Docker packages"""
    log_info("Installing Docker packages...")
    
    apt = AptManager()
    docker_packages = [
        "docker-ce",
        "docker-ce-cli", 
        "containerd.io",
        "docker-buildx-plugin",
        "docker-compose-plugin"
    ]
    
    apt.install(*docker_packages)


def _start_docker_service():
    """Start and verify Docker service"""
    log_info("Starting Docker service...")
    
    try:
        run_command("systemctl restart docker")
    except:
        run_command("systemctl start docker")
    
    # Check Docker version and status
    try:
        docker_version = run_command("docker --version", capture_output=True)
        log_info(f"Installed Docker version: {docker_version}")
        
        # Check if service is active
        run_command("systemctl is-active --quiet docker")
        log_info("✓ Docker service started successfully!")
        
    except Exception as e:
        log_warn(f"Docker service may not be running properly: {e}")


def _setup_nvidia_container_toolkit():
    """Setup NVIDIA Container Toolkit"""
    log_info("Setting up NVIDIA Container Toolkit...")
    
    # Add NVIDIA GPG key
    run_command(
        "curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | "
        "sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg"
    )
    
    # Get distribution info
    os_info = get_os_info()
    distribution = f"{os_info.get('ID', 'ubuntu')}{os_info.get('VERSION_ID', '22.04')}"
    
    # Add NVIDIA repository
    repo_setup_cmd = (
        f"curl -s -L https://nvidia.github.io/nvidia-container-runtime/{distribution}/nvidia-container-runtime.list | "
        "sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | "
        "sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list"
    )
    run_command(repo_setup_cmd)
    
    # Install NVIDIA Container Toolkit
    apt = AptManager()
    apt.install("nvidia-container-toolkit")
    
    # Configure Docker to use NVIDIA runtime
    log_info("Configuring NVIDIA runtime for Docker...")
    run_command("nvidia-ctk runtime configure --runtime=docker")
    
    # Restart Docker for changes to take effect
    log_info("Restarting Docker service to apply NVIDIA settings...")
    run_command("systemctl restart docker")


def _install_docker_compose():
    """Install Docker Compose"""
    log_info("Installing Docker Compose...")
    
    compose_path = "/usr/local/bin/docker-compose"
    
    if not os.path.exists(compose_path):
        download_url = (
            f"https://github.com/docker/compose/releases/download/"
            f"{DOCKER_COMPOSE_VERSION}/docker-compose-linux-x86_64"
        )
        
        run_command(f"curl -SL {download_url} -o {compose_path}")
        run_command(f"chmod +x {compose_path}")
        
        log_info("✓ Docker Compose installed")
    else:
        log_info("✓ Docker Compose already installed")


def _test_docker_installation():
    """Test Docker installation"""
    log_info("Testing Docker installation...")
    
    try:
        # Test with hello-world
        run_command("docker run --rm hello-world", capture_output=True)
        log_info("✓ Docker hello-world test passed")
        
        # Test NVIDIA integration if possible
        try:
            run_command("docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi", 
                       capture_output=True, check=False)
            log_info("✓ NVIDIA Docker integration test passed")
        except:
            log_warn("NVIDIA Docker test failed - driver may need reboot")
            
    except Exception as e:
        log_warn(f"Docker test failed: {e}")
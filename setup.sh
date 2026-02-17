#!/bin/bash
# NVIDIA Driver Setup - Entry Point
# This is the only script you need to run.

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${BLUE}${BOLD}"
echo "  ================================================================"
echo "     NVIDIA Driver Setup"
echo "     Hardware Acceleration for Media Servers"
echo "  ================================================================"
echo -e "${NC}"

# ── Root / sudo check ──────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}Error: This script must be run as root.${NC}"
    echo -e "  Usage: ${YELLOW}sudo bash setup.sh${NC}"
    exit 1
fi

# ── Python3 check ──────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}Error: Python 3 is required but not installed.${NC}"
    echo -e "  Install it with: ${YELLOW}sudo apt install -y python3${NC}"
    exit 1
fi

# ── Launch (try methods in order of preference) ───────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Method 1: pip-installed CLI command
if command -v nvidia-setup &>/dev/null; then
    echo -e "${GREEN}Found nvidia-setup command. Launching...${NC}"
    echo
    exec nvidia-setup "$@"
fi

# Method 2: Package installed, use python3 -m
if python3 -c "import nvidia_driver_setup" &>/dev/null 2>&1; then
    echo -e "${GREEN}Found nvidia_driver_setup package. Launching...${NC}"
    echo
    exec python3 -m nvidia_driver_setup "$@"
fi

# Method 3: Auto-install from source directory, then launch
if [[ -f "${SCRIPT_DIR}/pyproject.toml" ]]; then
    echo -e "${YELLOW}Package not installed. Installing...${NC}"

    # Try pip install, use --break-system-packages if needed (PEP 668)
    if pip install -e "${SCRIPT_DIR}" 2>/dev/null; then
        echo -e "${GREEN}Installed successfully.${NC}"
    elif pip install --break-system-packages -e "${SCRIPT_DIR}" 2>/dev/null; then
        echo -e "${GREEN}Installed successfully.${NC}"
    else
        echo -e "${YELLOW}pip install failed, running directly from source...${NC}"
        echo
        exec python3 "${SCRIPT_DIR}/main.py" "$@"
    fi

    echo
    # Use python -m since nvidia-setup may not be on PATH yet
    exec python3 -m nvidia_driver_setup "$@"
fi

# Method 4: Run from source directly (no pyproject.toml)
if [[ -f "${SCRIPT_DIR}/main.py" ]]; then
    echo -e "${GREEN}Running from source directory...${NC}"
    echo
    exec python3 "${SCRIPT_DIR}/main.py" "$@"
fi

echo -e "${RED}Error: Could not find nvidia-driver-setup.${NC}"
echo "  Clone the repo: git clone https://github.com/regix1/nvidia-driver-setup.git"
echo "  Then run: sudo bash setup.sh"
exit 1

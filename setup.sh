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

# Method 3: Run from source directory (backwards compatibility)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/main.py" ]]; then
    # Git check (only needed when running from source)
    if ! command -v git &>/dev/null; then
        echo -e "${RED}Error: Git is required but not installed.${NC}"
        echo -e "  Install it with: ${YELLOW}sudo apt install -y git${NC}"
        exit 1
    fi

    echo -e "${GREEN}Running from source directory. Launching...${NC}"
    echo
    exec python3 "${SCRIPT_DIR}/main.py" "$@"
fi

echo -e "${RED}Error: Could not find nvidia-driver-setup.${NC}"
echo "  Install it with: pip install nvidia-driver-setup"
echo "  Or run from the project directory: sudo bash setup.sh"
exit 1

#!/bin/bash
# Quick installer for NVIDIA Docker Setup

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                NVIDIA Docker Setup - Installer               ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo

# Determine if we need sudo
if [[ $EUID -eq 0 ]]; then
    SUDO=""
    PIP_FLAGS=""
else
    SUDO="sudo"
    PIP_FLAGS="--user"
fi

# Check for required tools
echo -e "${BLUE}Checking requirements...${NC}"

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is required but not installed.${NC}"
    echo "Please install Python 3 first:"
    echo "  ${SUDO} apt update && ${SUDO} apt install python3"
    exit 1
fi

if ! command -v git &> /dev/null; then
    echo -e "${YELLOW}Git not found, installing...${NC}"
    $SUDO apt update && $SUDO apt install -y git
fi

echo -e "${GREEN}✓ Requirements satisfied${NC}"

# Install Python dependencies
echo -e "${BLUE}Installing Python dependencies...${NC}"
if [[ -f "requirements.txt" ]]; then
    pip3 install $PIP_FLAGS -r requirements.txt
    echo -e "${GREEN}✓ Dependencies installed${NC}"
else
    echo -e "${YELLOW}Warning: requirements.txt not found, continuing...${NC}"
fi

# Check directory structure
echo -e "${BLUE}Checking project structure...${NC}"

required_dirs=("src" "templates" "configs")
required_files=("main.py" "src/utils/logging.py" "src/nvidia/drivers.py" "templates/plex-nvidia.yml")

for dir in "${required_dirs[@]}"; do
    if [[ ! -d "$dir" ]]; then
        echo -e "${RED}Error: Missing directory: $dir${NC}"
        echo "Please ensure you have the complete project files."
        exit 1
    fi
done

for file in "${required_files[@]}"; do
    if [[ ! -f "$file" ]]; then
        echo -e "${RED}Error: Missing file: $file${NC}"
        echo "Please ensure you have the complete project files."
        exit 1
    fi
done

echo -e "${GREEN}✓ Project structure verified${NC}"

# Make main.py executable
chmod +x main.py

echo
echo -e "${GREEN}Installation complete!${NC}"
echo
echo -e "${BLUE}Usage:${NC}"
if [[ $EUID -eq 0 ]]; then
    echo "  You're already root, run directly:"
    echo -e "    ${YELLOW}python3 main.py${NC}"
else
    echo "  Run the main script with sudo:"
    echo -e "    ${YELLOW}sudo python3 main.py${NC}"
fi
echo
echo -e "${BLUE}What this script will do:${NC}"
echo "  • Install NVIDIA drivers"
echo "  • Install Docker with NVIDIA support"
echo "  • Configure GPU acceleration for media servers"
echo "  • Apply optional NVENC/NvFBC patches"
echo

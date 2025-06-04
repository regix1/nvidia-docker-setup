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

# Check if running as root
if [[ $EUID -eq 0 ]]; then
    echo -e "${RED}Error: Do not run this installer as root!${NC}"
    echo -e "${YELLOW}This installer will use sudo when needed.${NC}"
    echo -e "${YELLOW}Please run as a regular user: ./install.sh${NC}"
    exit 1
fi

# Check for required tools
echo -e "${BLUE}Checking requirements...${NC}"

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is required but not installed.${NC}"
    echo "Please install Python 3 first:"
    echo "  sudo apt update && sudo apt install python3"
    exit 1
fi

if ! command -v git &> /dev/null; then
    echo -e "${YELLOW}Git not found, installing...${NC}"
    sudo apt update && sudo apt install -y git
fi

echo -e "${GREEN}✓ Requirements satisfied${NC}"

# Install Python dependencies
echo -e "${BLUE}Installing Python dependencies...${NC}"
if [[ -f "requirements.txt" ]]; then
    pip3 install --user -r requirements.txt
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
echo "  Run the main script with sudo:"
echo -e "    ${YELLOW}sudo python3 main.py${NC}"
echo
echo "  Or make it executable and run directly:"
echo -e "    ${YELLOW}sudo ./main.py${NC}"
echo
echo -e "${BLUE}What this script will do:${NC}"
echo "  • Install NVIDIA drivers"
echo "  • Install Docker with NVIDIA support"
echo "  • Configure GPU acceleration for media servers"
echo "  • Apply optional NVENC patches"
echo "  • Test GPU functionality"
echo
echo -e "${YELLOW}Note: You must run the main script as root (with sudo)${NC}"
echo
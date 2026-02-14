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
else
    SUDO="sudo"
fi

# Check for required tools
echo -e "${BLUE}Checking requirements...${NC}"

if ! command -v python3 &> /dev/null; then
    echo -e "${YELLOW}Python 3 not found, installing...${NC}"
    $SUDO apt update && $SUDO apt install -y python3
fi

if ! command -v git &> /dev/null; then
    echo -e "${YELLOW}Git not found, installing...${NC}"
    $SUDO apt update && $SUDO apt install -y git
fi

echo -e "${GREEN}✓ Requirements satisfied${NC}"

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

# Make scripts executable
chmod +x main.py
chmod +x scripts/*.sh 2>/dev/null || true

echo
echo -e "${GREEN}Ready to go!${NC}"
echo
echo -e "${BLUE}Usage:${NC}"
if [[ $EUID -eq 0 ]]; then
    echo -e "    ${YELLOW}python3 main.py${NC}"
else
    echo -e "    ${YELLOW}sudo python3 main.py${NC}"
fi
echo

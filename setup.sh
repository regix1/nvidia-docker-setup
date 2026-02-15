#!/bin/bash
# NVIDIA Docker Setup - Entry Point
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
echo "     NVIDIA Docker Setup"
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

# ── Git check ──────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    echo -e "${RED}Error: Git is required but not installed.${NC}"
    echo -e "  Install it with: ${YELLOW}sudo apt install -y git${NC}"
    exit 1
fi

# ── Verify main.py exists ─────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f "${SCRIPT_DIR}/main.py" ]]; then
    echo -e "${RED}Error: main.py not found in ${SCRIPT_DIR}${NC}"
    echo "  Please run this script from the project directory."
    exit 1
fi

# ── Launch ─────────────────────────────────────────────────────────
echo -e "${GREEN}All checks passed. Launching setup...${NC}"
echo
exec python3 "${SCRIPT_DIR}/main.py" "$@"

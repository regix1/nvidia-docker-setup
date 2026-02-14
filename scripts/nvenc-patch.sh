#!/bin/bash
#
# NVIDIA NVENC Session Limit Patch
#
# Patches libnvidia-encode.so to remove the artificial concurrent NVENC
# encoding session limit on consumer GeForce GPUs. Works by dynamically
# scanning the binary for the session-check pattern and applying a
# precise, anchor-based binary patch using Python3.
#
# Supports all modern NVIDIA driver versions by auto-detecting the
# specific byte pattern variant used in the installed driver.
#
# Usage:
#   sudo ./nvenc-patch.sh          # Apply patch
#   sudo ./nvenc-patch.sh -n       # Dry-run mode (no changes)
#   sudo ./nvenc-patch.sh -r       # Rollback from backup
#   sudo ./nvenc-patch.sh -v       # Verbose output
#   sudo ./nvenc-patch.sh -d VER   # Override driver version detection
#

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
BACKUP_DIR="/opt/nvidia/libnvidia-encode-backup"

# Flags
DRY_RUN=false
VERBOSE=false
ROLLBACK=false
MANUAL_VERSION=""

print_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[OK]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
print_verbose() { [[ "$VERBOSE" == true ]] && echo -e "${BLUE}[VERBOSE]${NC} $1" || true; }

usage() {
    cat << 'EOF'
Usage: nvenc-patch.sh [OPTIONS]

NVIDIA NVENC Session Limit Patch — removes the concurrent encoding
session limit on consumer GeForce GPUs.

OPTIONS:
    -n          Dry-run mode (analyse only, no changes)
    -r          Rollback/restore original library from backup
    -v          Verbose output
    -d VER      Override driver version (e.g. -d 580.126.09)
    -h          Show this help

EOF
    exit 0
}

get_driver_version() {
    if [[ -n "$MANUAL_VERSION" ]]; then
        echo "$MANUAL_VERSION"
        return 0
    fi

    if ! command -v nvidia-smi &>/dev/null; then
        print_error "nvidia-smi not found. Is the NVIDIA driver installed?"
        exit 1
    fi

    local ver
    ver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n1 | tr -d '[:space:]')

    if [[ -z "$ver" ]]; then
        print_error "Could not detect NVIDIA driver version"
        exit 1
    fi
    echo "$ver"
}

find_library() {
    local version=$1
    local search_paths=(
        "/usr/lib/x86_64-linux-gnu"
        "/usr/lib64"
        "/usr/lib"
        "/lib/x86_64-linux-gnu"
    )

    for dir in "${search_paths[@]}"; do
        local p="${dir}/libnvidia-encode.so.${version}"
        if [[ -f "$p" ]]; then
            echo "$p"
            return 0
        fi
    done

    # Fallback: broad search
    local found
    found=$(find /usr/lib* /lib* -name "libnvidia-encode.so.${version}" 2>/dev/null | head -n1)
    if [[ -n "$found" ]]; then
        echo "$found"
        return 0
    fi

    print_error "Could not find libnvidia-encode.so.${version}"
    exit 1
}

create_backup() {
    local lib_path=$1 driver_version=$2
    local backup_file="${BACKUP_DIR}/libnvidia-encode.so.${driver_version}.orig"

    mkdir -p "$BACKUP_DIR"

    if [[ -f "$backup_file" ]]; then
        print_verbose "Backup already exists: $backup_file"
        return 0
    fi

    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY-RUN] Would create backup: $backup_file"
        return 0
    fi

    cp -a "$lib_path" "$backup_file"
    print_success "Backup created: $backup_file"
}

restore_from_backup() {
    local lib_path=$1 driver_version=$2
    local backup_file="${BACKUP_DIR}/libnvidia-encode.so.${driver_version}.orig"

    if [[ ! -f "$backup_file" ]]; then
        print_error "No backup found at: $backup_file"
        exit 1
    fi

    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY-RUN] Would restore from backup"
        return 0
    fi

    cp -a "$backup_file" "$lib_path"
    ldconfig
    print_success "Restored from backup and ran ldconfig"
}

# ── Core: all scanning + patching lives in a single Python3 script ──

run_patcher() {
    local lib_path=$1
    local dry_run_flag="$DRY_RUN"
    local verbose_flag="$VERBOSE"

    python3 - "$lib_path" "$dry_run_flag" "$verbose_flag" << 'PYTHON_EOF'
import sys, os

lib_path   = sys.argv[1]
dry_run    = sys.argv[2].lower() == "true"
verbose    = sys.argv[3].lower() == "true"

# ── Pattern definitions ──────────────────────────────────────────────
# Each entry: (anchor_hex, description, [(old_hex, new_hex, label), ...])
#
# The anchor is a byte sequence that uniquely locates the session-limit
# check in the binary.  We try anchors in order; the first unique match
# wins.  "old/new" pairs are tried at (anchor_offset + skip) where
# skip = number of leading anchor bytes before the patchable region.
#
# Assembly being patched (conceptually):
#   call  <session_check>   ; e8 XX XX fe ff   ← tail of anchor
#   mov   r1Xd, eax         ; 41 89 cX         ← register varies
#   test  eax, eax          ; 85 c0
#   jne   <error>           ; 0f 85 XX XX XX XX (may be absent)
#
# We replace   mov rXd,eax ; test eax,eax [; jne ...]
# with         sub eax,eax ; mov  rXd,eax [; nop*6]

ANCHORS = [
    # Variant A: result stored in R14D (mov r14d,eax = 41 89 c6)
    {
        "anchor": "feff4189c685c0",
        "skip": 2,
        "patched_marker": "feff29c04189c6",
        "variants": [
            ("4189c685c00f85a6000000", "29c04189c690909090909090", "r14d+JNE"),
            ("4189c685c0",             "29c04189c6",               "r14d"),
        ],
    },
    # Variant B: test before mov, result stored in R12D (mov r12d,eax = 41 89 c4)
    {
        "anchor": "feff85c04189c4",
        "skip": 2,
        "patched_marker": "feff29c04189c4",
        "variants": [
            ("85c04189c4", "29c04189c4", "r12d-test-first"),
        ],
    },
    # Variant C: mov before test, result stored in R12D
    {
        "anchor": "feff4189c485c0",
        "skip": 2,
        "patched_marker": "feff29c04189c4",
        "variants": [
            ("4189c485c00f85", "29c04189c49090", "r12d+JNE"),
            ("4189c485c0",     "29c04189c4",     "r12d"),
        ],
    },
]

def find_all(data: bytes, pattern: bytes) -> list[int]:
    positions, start = [], 0
    while True:
        pos = data.find(pattern, start)
        if pos == -1:
            return positions
        positions.append(pos)
        start = pos + 1

def vprint(msg):
    if verbose:
        print(f"  [verbose] {msg}")

# ── Read binary ──────────────────────────────────────────────────────
try:
    with open(lib_path, "rb") as f:
        data = bytearray(f.read())
except Exception as e:
    print(f"ERROR: Cannot read {lib_path}: {e}", file=sys.stderr)
    sys.exit(1)

vprint(f"Library size: {len(data)} bytes")

# ── Scan for matching anchor ─────────────────────────────────────────
matched_anchor = None
anchor_pos     = -1

for entry in ANCHORS:
    anchor_bytes = bytes.fromhex(entry["anchor"])
    hits = find_all(data, anchor_bytes)
    vprint(f"Anchor {entry['anchor']}: {len(hits)} hit(s)")

    if len(hits) == 1:
        matched_anchor = entry
        anchor_pos = hits[0]
        break
    elif len(hits) > 1:
        vprint(f"  ↳ Skipping (ambiguous: offsets {[hex(h) for h in hits]})")

    # Also check patched marker (already applied?)
    marker_bytes = bytes.fromhex(entry["patched_marker"])
    if data.find(marker_bytes) != -1:
        print("ALREADY_PATCHED")
        sys.exit(0)

if matched_anchor is None:
    # One more sweep: maybe it's already patched with a different anchor
    for entry in ANCHORS:
        marker_bytes = bytes.fromhex(entry["patched_marker"])
        if data.find(marker_bytes) != -1:
            print("ALREADY_PATCHED")
            sys.exit(0)

    print("ERROR: No unique anchor pattern found in binary.", file=sys.stderr)
    print("ERROR: This driver version may not be supported.", file=sys.stderr)
    sys.exit(1)

patch_start = anchor_pos + matched_anchor["skip"]
vprint(f"Anchor matched at offset {hex(anchor_pos)}, patch region starts at {hex(patch_start)}")

# ── Try each variant at the patch location ───────────────────────────
applied = False
for old_hex, new_hex, label in matched_anchor["variants"]:
    old_bytes = bytes.fromhex(old_hex)
    new_bytes = bytes.fromhex(new_hex)
    actual    = bytes(data[patch_start : patch_start + len(old_bytes)])

    if actual == old_bytes:
        print(f"MATCH: variant={label}  offset={hex(patch_start)}  len={len(old_bytes)}")
        vprint(f"Old: {old_hex}")
        vprint(f"New: {new_hex}")

        if dry_run:
            print("DRY_RUN: patch would succeed")
            sys.exit(0)

        data[patch_start : patch_start + len(old_bytes)] = new_bytes
        applied = True
        break

    if actual == new_bytes:
        print("ALREADY_PATCHED")
        sys.exit(0)

if not applied:
    region = bytes(data[patch_start : patch_start + 16])
    print(f"ERROR: No variant matched at {hex(patch_start)}", file=sys.stderr)
    print(f"ERROR: Bytes found: {region.hex()}", file=sys.stderr)
    sys.exit(1)

# ── Write patched binary ─────────────────────────────────────────────
try:
    with open(lib_path, "wb") as f:
        f.write(data)
    print("PATCHED_OK")
except Exception as e:
    print(f"ERROR: Failed to write: {e}", file=sys.stderr)
    sys.exit(1)
PYTHON_EOF
}

# ── Main ─────────────────────────────────────────────────────────────

main() {
    while getopts "nrvhd:" opt; do
        case $opt in
            n) DRY_RUN=true ;;
            r) ROLLBACK=true ;;
            v) VERBOSE=true ;;
            d) MANUAL_VERSION="$OPTARG" ;;
            h) usage ;;
            *) usage ;;
        esac
    done

    echo
    print_info "NVIDIA NVENC Session Limit Patch"
    echo

    # Root check
    if [[ $EUID -ne 0 ]]; then
        print_error "This script must be run as root (use sudo)"
        exit 1
    fi

    # Python check
    if ! command -v python3 &>/dev/null; then
        print_error "python3 is required but not found"
        exit 1
    fi

    # Driver version
    print_info "Detecting driver version..."
    DRIVER_VERSION=$(get_driver_version)
    print_success "Driver version: $DRIVER_VERSION"

    # Find library
    print_info "Locating libnvidia-encode.so..."
    LIB_PATH=$(find_library "$DRIVER_VERSION")
    print_success "Library: $LIB_PATH"

    # Rollback
    if [[ "$ROLLBACK" == true ]]; then
        restore_from_backup "$LIB_PATH" "$DRIVER_VERSION"
        exit 0
    fi

    # Backup
    create_backup "$LIB_PATH" "$DRIVER_VERSION"

    # Patch
    print_info "Scanning binary for session-limit pattern..."

    set +e
    RESULT=$(run_patcher "$LIB_PATH" 2>&1)
    PATCHER_RC=$?
    set -e

    if [[ "$VERBOSE" == true ]]; then
        echo "$RESULT" | while IFS= read -r line; do print_verbose "$line"; done
    fi

    if echo "$RESULT" | grep -q "ALREADY_PATCHED"; then
        print_success "Library is already patched — nothing to do"
        exit 0
    fi

    if echo "$RESULT" | grep -q "DRY_RUN"; then
        print_info "[DRY-RUN] Pattern found — patch would succeed"
        exit 0
    fi

    if echo "$RESULT" | grep -q "PATCHED_OK"; then
        ldconfig
        echo
        print_success "NVENC session limit removed!"
        print_info "Backup: ${BACKUP_DIR}/libnvidia-encode.so.${DRIVER_VERSION}.orig"
        print_info "Rollback: sudo $0 -r"
        echo
        print_warning "Restart any running NVENC applications / Docker containers."
        exit 0
    fi

    # If we get here, something went wrong
    print_error "Patch failed (exit code: $PATCHER_RC)"
    echo "$RESULT" | grep -i "error" || true
    exit 1
}

main "$@"

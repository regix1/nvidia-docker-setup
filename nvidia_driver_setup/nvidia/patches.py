"""NVIDIA driver patches for NVENC and NvFBC

Uses pure-Python binary patching for NVENC session limit removal.
Does NOT use sed-based patching (regix1/nvidia-patch approach) which
corrupts ELF SONAME metadata and breaks nvidia-container-cli library
discovery and ldconfig symlink creation.
"""

import glob
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Optional

from ..utils.logging import log_info, log_step, log_warn, log_success, log_error
from ..utils.prompts import prompt_yes_no
from ..utils.system import run_command


# Regex that matches a valid NVIDIA driver version string (e.g. 580.126.09)
_VERSION_PATTERN = re.compile(r'^[0-9]+\.[0-9]+')

# Professional GPU name patterns (these GPUs have unrestricted NVENC sessions)
_PROFESSIONAL_GPU_PATTERNS: list[str] = [
    "quadro", "tesla", "rtx a", "rtx pro",
    " a100", " a40", " a30", " a16", " a10", " a2",
    " l40", " l20", " l4", " l2",
    " h100", " h200", " b100", " b200",
]

# Driver version thresholds for consumer NVENC session limits (Linux)
_NVENC_LIMIT_12_MIN_DRIVER = 590
_NVENC_LIMIT_5_MIN_DRIVER = 531
_NVENC_LIMIT_3_MIN_DRIVER = 450

# Backup directory for original libnvidia-encode.so files
_BACKUP_DIR = "/opt/nvidia/libnvidia-encode-backup"

# Standard library search paths (ordered by preference)
_LIBRARY_SEARCH_PATHS: list[str] = [
    "/usr/lib/x86_64-linux-gnu",
    "/usr/lib64",
    "/usr/lib",
    "/lib/x86_64-linux-gnu",
]


# ── Binary patch anchor definitions ─────────────────────────────────
#
# Each entry describes a byte-sequence "anchor" that uniquely locates the
# NVENC session-limit check in libnvidia-encode.so.
#
# Assembly being patched (conceptually):
#   call  <session_check>   ; e8 XX XX fe ff   <- tail of anchor
#   mov   r1Xd, eax         ; 41 89 cX         <- register varies
#   test  eax, eax          ; 85 c0
#   jne   <error>           ; 0f 85 XX XX XX XX (may be absent)
#
# We replace   mov rXd,eax ; test eax,eax [; jne ...]
# with         sub eax,eax ; mov  rXd,eax [; nop*6]
#
# Anchors are tried in order; the first unique (exactly one hit) match wins.
# "skip" = number of leading anchor bytes before the patchable region.

@dataclass(frozen=True)
class PatchVariant:
    """A single old -> new byte replacement at the patch site."""
    old_hex: str
    new_hex: str
    label: str


@dataclass(frozen=True)
class AnchorPattern:
    """An anchor byte sequence and its associated patch variants."""
    anchor: str
    skip: int
    patched_marker: str
    variants: list[PatchVariant] = field(default_factory=list)


_ANCHORS: list[AnchorPattern] = [
    # Variant A: result stored in R14D (mov r14d,eax = 41 89 c6)
    # Used by 580.x+ drivers
    AnchorPattern(
        anchor="feff4189c685c0",
        skip=2,
        patched_marker="feff29c04189c6",
        variants=[
            PatchVariant("4189c685c00f85a6000000", "29c04189c690909090909090", "r14d+JNE"),
            PatchVariant("4189c685c0",             "29c04189c6",               "r14d"),
        ],
    ),
    # Variant B: test before mov, result stored in R12D (mov r12d,eax = 41 89 c4)
    # Used by some 570.x drivers
    AnchorPattern(
        anchor="feff85c04189c4",
        skip=2,
        patched_marker="feff29c04189c4",
        variants=[
            PatchVariant("85c04189c4", "29c04189c4", "r12d-test-first"),
        ],
    ),
    # Variant C: mov before test, result stored in R12D
    # Used by older 570.x and earlier drivers
    AnchorPattern(
        anchor="feff4189c485c0",
        skip=2,
        patched_marker="feff29c04189c4",
        variants=[
            PatchVariant("4189c485c00f85", "29c04189c49090", "r12d+JNE"),
            PatchVariant("4189c485c0",     "29c04189c4",     "r12d"),
        ],
    ),
]


@dataclass
class PatchResult:
    """Result of a binary patch operation."""
    success: bool
    already_patched: bool
    variant_label: str
    offset: int
    message: str


# ── Driver version detection ────────────────────────────────────────

def _detect_driver_version(manual_version: Optional[str] = None, verbose: bool = False) -> Optional[str]:
    """Detect the installed NVIDIA driver version using multiple fallback methods.

    Tries the following sources in order and returns the first valid version
    string found:
        1. nvidia-smi query
        2. libnvidia-encode.so.* filename on disk
        3. modinfo nvidia kernel module
        4. dpkg package database

    Args:
        manual_version: If provided, skip detection and use this version directly.
        verbose: If True, log detailed detection steps.

    Returns:
        Driver version string (e.g. "580.126.09") or None if all methods fail.
    """
    if manual_version is not None:
        return manual_version

    # Method 1: nvidia-smi (preferred, but fails after driver upgrade without reboot)
    try:
        result = subprocess.run(
            "nvidia-smi --query-gpu=driver_version --format=csv,noheader",
            shell=True,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            ver = result.stdout.strip()
            if ver and _VERSION_PATTERN.match(ver):
                if verbose:
                    log_info(f"Driver version detected via nvidia-smi: {ver}")
                return ver
            if ver:
                if verbose:
                    log_info(f"nvidia-smi returned invalid version string: {ver}")
        log_warn("nvidia-smi failed or returned invalid output (driver/library version mismatch?)")
    except OSError:
        pass

    # Method 2: Parse from installed libnvidia-encode.so filename (pick highest version)
    version_from_lib = _detect_version_from_library()
    if version_from_lib is not None:
        if verbose:
            log_info(f"Driver version detected via library filename: {version_from_lib}")
        log_warn("Detected driver version from library filename (nvidia-smi unavailable)")
        return version_from_lib

    # Method 3: modinfo nvidia
    try:
        result = subprocess.run(
            "modinfo nvidia",
            shell=True,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("version:"):
                    parts = line.split(None, 1)
                    ver = parts[1].strip() if len(parts) > 1 else ""
                    if ver and _VERSION_PATTERN.match(ver):
                        if verbose:
                            log_info(f"Driver version detected via modinfo: {ver}")
                        log_warn("Detected driver version from kernel module info (nvidia-smi unavailable)")
                        return ver
    except OSError:
        pass

    # Method 4: dpkg
    try:
        result = subprocess.run(
            "dpkg -l 'nvidia-driver-*'",
            shell=True,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split()
                if (
                    len(parts) >= 3
                    and parts[0] == "ii"
                    and re.match(r'^nvidia-driver-[0-9]+$', parts[1])
                ):
                    match = re.match(r'^[0-9]+\.[0-9]+\.[0-9]+', parts[2])
                    if match:
                        ver = match.group(0)
                        if verbose:
                            log_info(f"Driver version detected via dpkg: {ver}")
                        log_warn("Detected driver version from dpkg package info (nvidia-smi unavailable)")
                        return ver
    except OSError:
        pass

    return None


def _detect_version_from_library() -> Optional[str]:
    """Parse driver version from the libnvidia-encode.so filename on disk.

    Scans common library directories for libnvidia-encode.so.X.Y.Z and
    extracts the version from the filename.  Returns the highest version
    found, or None.
    """
    search_dirs = _LIBRARY_SEARCH_PATHS + [
        "/lib64",
        "/lib",
    ]

    all_versions: list[str] = []
    for search_dir in search_dirs:
        pattern = os.path.join(search_dir, "libnvidia-encode.so.*.*.*")
        for path in glob.glob(pattern):
            ver_match = re.search(r'\.so\.([0-9]+\.[0-9]+\.[0-9]+)', os.path.basename(path))
            if ver_match:
                all_versions.append(ver_match.group(1))

    if all_versions:
        # Sort by version tuple to pick the highest installed version
        all_versions.sort(key=lambda v: tuple(int(x) for x in v.split('.')), reverse=True)
        return all_versions[0]

    return None


# ── GPU architecture detection ─────────────────────────────────────

def _detect_gpu_architecture() -> Optional[tuple[str, float]]:
    """Detect the GPU architecture name and compute capability.

    Uses nvidia-smi to query the compute capability of the first GPU.

    Returns:
        Tuple of (architecture_name, compute_capability) or None if detection fails.
    """
    try:
        result = subprocess.run(
            "nvidia-smi --query-gpu=compute_cap --format=csv,noheader",
            shell=True,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        cap_str = result.stdout.strip().split('\n')[0].strip()
        if not cap_str:
            return None
        compute_cap = float(cap_str)

        # Map compute capability to architecture name
        arch_map: dict[str, tuple[float, float]] = {
            "Tesla":        (1.0, 1.3),
            "Fermi":        (2.0, 2.1),
            "Kepler":       (3.0, 3.7),
            "Maxwell":      (5.0, 5.3),
            "Pascal":       (6.0, 6.2),
            "Volta":        (7.0, 7.0),
            "Turing":       (7.5, 7.5),
            "Ampere":       (8.0, 8.6),
            "Ada Lovelace": (8.9, 8.9),
            "Blackwell":    (10.0, 10.9),
        }
        for arch_name, (low, high) in arch_map.items():
            if low <= compute_cap <= high:
                return (arch_name, compute_cap)

        return ("Unknown", compute_cap)
    except (OSError, ValueError):
        return None


def _is_professional_gpu() -> bool:
    """Check if the installed GPU is a professional/datacenter model.

    Professional GPUs (Quadro, Tesla, RTX A-series, RTX PRO, L-series, etc.)
    have unrestricted NVENC sessions and never need patching.
    """
    try:
        result = subprocess.run(
            "nvidia-smi --query-gpu=name --format=csv,noheader",
            shell=True,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False
        gpu_name = result.stdout.strip().split('\n')[0].lower()
        return any(pattern in gpu_name for pattern in _PROFESSIONAL_GPU_PATTERNS)
    except OSError:
        return False


def get_nvenc_session_info() -> dict:
    """Return NVENC session status for the current GPU and driver.

    Returns:
        Dict with keys:
            native_limit: int or None (12, 5, 3, or None for unrestricted)
            is_patched: bool
            is_professional: bool
            driver_version: str or None
            status_label: str  (e.g. "[12 sessions]", "[Unlimited]", "[Pro]")
            patch_useful: bool (True if patching would increase sessions)
    """
    info: dict = {
        'native_limit': None,
        'is_patched': False,
        'is_professional': False,
        'driver_version': None,
        'status_label': '',
        'patch_useful': False,
    }

    # Detect driver version
    driver_version = _detect_driver_version(verbose=False)
    info['driver_version'] = driver_version

    # Professional GPU check
    if _is_professional_gpu():
        info['is_professional'] = True
        info['status_label'] = "[Pro - Unrestricted]"
        info['patch_useful'] = False
        return info

    # Check if already patched
    is_patched = False
    try:
        for search_path in _LIBRARY_SEARCH_PATHS:
            pattern = os.path.join(search_path, "libnvidia-encode.so.???.*")
            libs = glob.glob(pattern)
            if libs:
                result = _patch_binary(libs[0], dry_run=True, verbose=False)
                is_patched = result.already_patched
                break
    except Exception:
        pass

    info['is_patched'] = is_patched

    if is_patched:
        info['status_label'] = "[Unlimited]"
        info['patch_useful'] = False
        return info

    # Determine native limit from driver version
    if driver_version:
        try:
            major = int(driver_version.split('.')[0])
        except (ValueError, IndexError):
            major = 0

        if major >= _NVENC_LIMIT_12_MIN_DRIVER:
            info['native_limit'] = 12
            info['status_label'] = "[12 sessions]"
        elif major >= _NVENC_LIMIT_5_MIN_DRIVER:
            info['native_limit'] = 5
            info['status_label'] = "[5 sessions]"
        elif major >= _NVENC_LIMIT_3_MIN_DRIVER:
            info['native_limit'] = 3
            info['status_label'] = "[3 sessions]"
        else:
            info['native_limit'] = 3
            info['status_label'] = "[Limited]"
    else:
        info['status_label'] = "[Unknown]"

    info['patch_useful'] = True
    return info


def _gpu_needs_nvenc_patch() -> bool:
    """Check whether the installed GPU needs the NVENC session limit patch.

    Professional GPUs (Quadro, Tesla, RTX A/PRO, etc.) have unrestricted
    NVENC sessions and never need patching.  All consumer GeForce GPUs
    have a driver-enforced session cap (12 on driver 590+, fewer on older
    drivers) and benefit from patching.

    Returns:
        True if the GPU needs/benefits from the patch, False for pro GPUs.
    """
    if _is_professional_gpu():
        log_info("Professional GPU detected -- NVENC sessions are unrestricted")
        return False

    return True


# ── ELF SONAME verification ───────────────────────────────────────

def _verify_elf_soname(lib_path: str) -> Optional[str]:
    """Verify that the ELF SONAME field is intact in a shared library.

    The SONAME is critical for ldconfig, nvidia-container-cli, and the
    dynamic linker. If it's missing, the library becomes invisible to
    the entire NVIDIA container toolkit chain.

    Args:
        lib_path: Absolute path to the .so file to check.

    Returns:
        The SONAME string if found, or None if missing/corrupted.
    """
    try:
        result = subprocess.run(
            ["readelf", "-d", lib_path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            if "SONAME" in line:
                # Extract the SONAME value: [libnvidia-encode.so.1]
                match = re.search(r'\[(.*?)\]', line)
                if match:
                    return match.group(1)
        return None
    except OSError:
        return None


# ── Library locating ────────────────────────────────────────────────

def _find_encode_library(version: str) -> Optional[str]:
    """Search standard library paths for libnvidia-encode.so.VERSION.

    Checks well-known directories first, then falls back to a broad search
    under /usr/lib* and /lib*.

    Args:
        version: Driver version string (e.g. "580.126.09").

    Returns:
        Absolute path to the library file, or None if not found.
    """
    target_name = f"libnvidia-encode.so.{version}"

    # Check well-known paths first
    for dir_path in _LIBRARY_SEARCH_PATHS:
        candidate = os.path.join(dir_path, target_name)
        if os.path.isfile(candidate):
            return candidate

    # Fallback: broad search under /usr/lib* and /lib*
    for prefix in ["/usr/lib", "/lib"]:
        try:
            parent = os.path.dirname(prefix)  # "/" for both
            for entry in os.listdir(parent if parent != "" else "/"):
                full_dir = os.path.join(parent if parent != "" else "/", entry)
                if not entry.startswith(os.path.basename(prefix)):
                    continue
                if not os.path.isdir(full_dir):
                    continue
                candidate = os.path.join(full_dir, target_name)
                if os.path.isfile(candidate):
                    return candidate
        except OSError:
            continue

    return None


# ── Backup / restore ────────────────────────────────────────────────

def _create_backup(lib_path: str, version: str, dry_run: bool = False) -> bool:
    """Back up the original libnvidia-encode.so to the backup directory.

    Creates /opt/nvidia/libnvidia-encode-backup/ if needed.  Skips silently
    if a backup for this version already exists.

    Args:
        lib_path: Absolute path to the library to back up.
        version: Driver version string (used in the backup filename).
        dry_run: If True, only log what would happen.

    Returns:
        True if backup exists (or was created), False on failure.
    """
    backup_file = os.path.join(_BACKUP_DIR, f"libnvidia-encode.so.{version}.orig")

    if os.path.isfile(backup_file):
        log_info(f"Backup already exists: {backup_file}")
        return True

    if dry_run:
        log_info(f"[DRY-RUN] Would create backup: {backup_file}")
        return True

    try:
        os.makedirs(_BACKUP_DIR, exist_ok=True)
        shutil.copy2(lib_path, backup_file)
        log_success(f"Backup created: {backup_file}")
        return True
    except OSError as exc:
        log_error(f"Failed to create backup: {exc}")
        return False


def _restore_backup(version: str, lib_path: str, dry_run: bool = False) -> bool:
    """Restore the original libnvidia-encode.so from backup.

    Copies the backup file back over the current library and runs ldconfig
    to rebuild the dynamic linker cache.

    Args:
        version: Driver version string.
        lib_path: Absolute path to the library to restore.
        dry_run: If True, only log what would happen.

    Returns:
        True on success, False if backup not found or copy failed.
    """
    backup_file = os.path.join(_BACKUP_DIR, f"libnvidia-encode.so.{version}.orig")

    if not os.path.isfile(backup_file):
        log_error(f"No backup found at: {backup_file}")
        return False

    if dry_run:
        log_info("[DRY-RUN] Would restore from backup")
        return True

    try:
        shutil.copy2(backup_file, lib_path)
        run_command("ldconfig", check=False)
        log_success("Restored from backup and ran ldconfig")
        return True
    except OSError as exc:
        log_error(f"Failed to restore from backup: {exc}")
        return False


# ── Binary patcher ──────────────────────────────────────────────────

def _find_all_occurrences(data: bytes, pattern: bytes) -> list[int]:
    """Find all byte-level occurrences of pattern in data.

    Args:
        data: The binary data to search.
        pattern: The byte pattern to locate.

    Returns:
        List of starting offsets where pattern was found.
    """
    positions: list[int] = []
    start = 0
    while True:
        pos = data.find(pattern, start)
        if pos == -1:
            return positions
        positions.append(pos)
        start = pos + 1


def _patch_binary(lib_path: str, dry_run: bool = False, verbose: bool = False) -> PatchResult:
    """Scan a libnvidia-encode.so binary and patch the session-limit check.

    Reads the binary, scans for known anchor byte sequences, and replaces
    the session-limit check instructions with a forced-success pattern.

    The patcher tries each anchor pattern in order.  The first anchor that
    produces exactly one unique match in the binary is used.  If no anchor
    matches uniquely, the binary is checked for already-patched markers.

    Args:
        lib_path: Absolute path to the library to patch.
        dry_run: If True, analyse only -- do not write changes.
        verbose: If True, log detailed scanning information.

    Returns:
        PatchResult describing the outcome.
    """
    # Read the binary
    try:
        with open(lib_path, "rb") as fh:
            data = bytearray(fh.read())
    except OSError as exc:
        return PatchResult(
            success=False,
            already_patched=False,
            variant_label="",
            offset=-1,
            message=f"Cannot read {lib_path}: {exc}",
        )

    if verbose:
        log_info(f"Library size: {len(data)} bytes")

    # Scan for a matching anchor
    matched_anchor: Optional[AnchorPattern] = None
    anchor_pos: int = -1

    for entry in _ANCHORS:
        anchor_bytes = bytes.fromhex(entry.anchor)
        hits = _find_all_occurrences(data, anchor_bytes)
        if verbose:
            log_info(f"Anchor {entry.anchor}: {len(hits)} hit(s)")

        if len(hits) == 1:
            matched_anchor = entry
            anchor_pos = hits[0]
            break
        elif len(hits) > 1:
            if verbose:
                log_info(f"  Skipping (ambiguous: offsets {[hex(h) for h in hits]})")

        # Check if already patched with this anchor's marker
        marker_bytes = bytes.fromhex(entry.patched_marker)
        if data.find(marker_bytes) != -1:
            return PatchResult(
                success=True,
                already_patched=True,
                variant_label="",
                offset=-1,
                message="Library is already patched",
            )

    if matched_anchor is None:
        # One more sweep: maybe it is already patched with a different anchor
        for entry in _ANCHORS:
            marker_bytes = bytes.fromhex(entry.patched_marker)
            if data.find(marker_bytes) != -1:
                return PatchResult(
                    success=True,
                    already_patched=True,
                    variant_label="",
                    offset=-1,
                    message="Library is already patched",
                )

        return PatchResult(
            success=False,
            already_patched=False,
            variant_label="",
            offset=-1,
            message="No unique anchor pattern found in binary. This driver version may not be supported.",
        )

    patch_start = anchor_pos + matched_anchor.skip
    if verbose:
        log_info(f"Anchor matched at offset {hex(anchor_pos)}, patch region starts at {hex(patch_start)}")

    # Try each variant at the patch location
    for variant in matched_anchor.variants:
        old_bytes = bytes.fromhex(variant.old_hex)
        new_bytes = bytes.fromhex(variant.new_hex)
        actual = bytes(data[patch_start : patch_start + len(old_bytes)])

        if actual == old_bytes:
            if verbose:
                log_info(f"MATCH: variant={variant.label}  offset={hex(patch_start)}  len={len(old_bytes)}")
                log_info(f"Old: {variant.old_hex}")
                log_info(f"New: {variant.new_hex}")

            if dry_run:
                return PatchResult(
                    success=True,
                    already_patched=False,
                    variant_label=variant.label,
                    offset=patch_start,
                    message="[DRY-RUN] Pattern found -- patch would succeed",
                )

            # Apply the patch
            data[patch_start : patch_start + len(old_bytes)] = new_bytes

            # Write back
            try:
                with open(lib_path, "wb") as fh:
                    fh.write(data)
            except OSError as exc:
                return PatchResult(
                    success=False,
                    already_patched=False,
                    variant_label=variant.label,
                    offset=patch_start,
                    message=f"Failed to write patched binary: {exc}",
                )

            return PatchResult(
                success=True,
                already_patched=False,
                variant_label=variant.label,
                offset=patch_start,
                message=f"Patched variant {variant.label} at offset {hex(patch_start)}",
            )

        if actual == new_bytes:
            return PatchResult(
                success=True,
                already_patched=True,
                variant_label=variant.label,
                offset=patch_start,
                message="Library is already patched",
            )

    # No variant matched at the patch location
    region = bytes(data[patch_start : patch_start + 16])
    return PatchResult(
        success=False,
        already_patched=False,
        variant_label="",
        offset=patch_start,
        message=f"No variant matched at {hex(patch_start)}. Bytes found: {region.hex()}",
    )


# ── Public entry points ─────────────────────────────────────────────

def apply_nvidia_patches() -> None:
    """Apply NVIDIA patches for unlimited NVENC sessions"""
    log_step("NVIDIA NVENC & NvFBC unlimited sessions patch...")

    session_info = get_nvenc_session_info()

    if session_info['is_professional']:
        log_success("Professional GPU detected -- NVENC sessions are already unrestricted")
        log_info("No NVENC patch needed")
    elif session_info['is_patched']:
        log_success("NVENC is already patched -- sessions are unlimited")
    else:
        limit = session_info['native_limit']
        if limit and limit >= 12:
            log_info(f"Your GPU currently supports {limit} concurrent NVENC sessions")
            log_info("Patching removes this limit entirely (unlimited sessions)")
            if not prompt_yes_no("Apply patch for unlimited NVENC sessions?"):
                if prompt_yes_no("Would you like to patch for NvFBC support (useful for OBS)?"):
                    _apply_nvfbc_patch()
                return
        else:
            if not prompt_yes_no("Would you like to patch NVIDIA drivers to remove NVENC session limit?"):
                return

        _apply_nvenc_patch()

    if prompt_yes_no("Would you also like to patch for NvFBC support (useful for OBS)?"):
        _apply_nvfbc_patch()


def _nvidia_smi_works() -> bool:
    """Check whether nvidia-smi can successfully query the driver.

    Returns False if nvidia-smi is missing, exits non-zero, or reports a
    driver/library version mismatch (common after upgrading without reboot).
    """
    try:
        result = subprocess.run(
            "nvidia-smi --query-gpu=driver_version --format=csv,noheader",
            shell=True,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False
        output = result.stdout.strip()
        if not output:
            return False
        # After tr -d of whitespace, a mismatch error becomes a long non-version string
        if "mismatch" in output.lower() or "failed" in output.lower():
            return False
        return bool(_VERSION_PATTERN.match(output))
    except OSError:
        return False


def _needs_reboot() -> bool:
    """Check if nvidia-smi indicates a driver/library version mismatch.

    This happens when the userspace libraries have been upgraded but the
    kernel module is still the old version -- a reboot is required.
    """
    try:
        result = subprocess.run(
            "nvidia-smi",
            shell=True,
            capture_output=True,
            text=True,
        )
        combined = result.stdout + result.stderr
        return "Driver/library version mismatch" in combined
    except OSError:
        return False


def _apply_nvenc_patch(
    dry_run: bool = False,
    rollback: bool = False,
    verbose: bool = True,
    manual_version: Optional[str] = None,
) -> None:
    """Apply NVENC session limit patch using pure-Python binary patcher.

    Uses anchor-based byte scanning to precisely locate and patch the
    session-limit check in libnvidia-encode.so.  Automatically detects
    the byte-pattern variant for the installed driver version.

    This patcher reads and writes raw bytes -- it does NOT use sed-based
    patching (which corrupts ELF SONAME metadata and breaks container
    library mounting via nvidia-container-cli).

    When nvidia-smi is broken (e.g. after driver upgrade without reboot),
    detects the version via fallback methods.

    Args:
        dry_run: If True, analyse only -- do not modify the binary.
        rollback: If True, restore the original library from backup.
        verbose: If True, log detailed scanning information.
        manual_version: If provided, skip detection and use this version.
    """
    log_info("NVIDIA NVENC Session Limit Patch")

    # ── Check if GPU even needs the patch ──────────────────────────
    if not rollback and not _gpu_needs_nvenc_patch():
        log_success("Your GPU supports unlimited NVENC sessions natively -- no patch needed")
        return

    # ── Detect driver version ───────────────────────────────────────
    log_info("Detecting driver version...")
    driver_version = _detect_driver_version(manual_version=manual_version, verbose=verbose)

    if driver_version is None:
        log_error("Could not detect NVIDIA driver version via any method")
        log_error("Tried: nvidia-smi, library filename, modinfo, dpkg")
        log_warn("Please reboot and re-run, or pass version manually")
        return

    log_success(f"Driver version: {driver_version}")

    # ── Find library ────────────────────────────────────────────────
    log_info("Locating libnvidia-encode.so...")
    lib_path = _find_encode_library(driver_version)

    if lib_path is None:
        log_error(f"Could not find libnvidia-encode.so.{driver_version}")
        log_warn("Ensure the driver is properly installed: apt reinstall libnvidia-encode-" +
                 driver_version.split('.')[0])
        return

    log_success(f"Library: {lib_path}")

    # ── Verify SONAME before touching anything ─────────────────────
    soname_before = _verify_elf_soname(lib_path)
    if soname_before:
        if verbose:
            log_info(f"ELF SONAME verified: {soname_before}")
    else:
        log_warn("ELF SONAME is already missing from this library!")
        log_warn("This may indicate a previous sed-based patch corrupted the file")
        log_warn(f"Consider: apt reinstall libnvidia-encode-{driver_version.split('.')[0]}")
        if not rollback:
            return

    # ── Rollback mode ───────────────────────────────────────────────
    if rollback:
        if _restore_backup(driver_version, lib_path, dry_run=dry_run):
            # Verify SONAME is restored
            if not dry_run:
                soname_after = _verify_elf_soname(lib_path)
                if soname_after:
                    log_success(f"SONAME verified after rollback: {soname_after}")
                else:
                    log_warn("SONAME still missing after rollback -- backup may also be corrupted")
                    log_warn(f"Reinstall the package: apt reinstall libnvidia-encode-{driver_version.split('.')[0]}")
            return
        log_error("Rollback failed")
        return

    # ── Backup ──────────────────────────────────────────────────────
    if not _create_backup(lib_path, driver_version, dry_run=dry_run):
        log_error("Cannot proceed without a backup")
        return

    # ── Patch ───────────────────────────────────────────────────────
    log_info("Scanning binary for session-limit pattern...")

    patch_result = _patch_binary(lib_path, dry_run=dry_run, verbose=verbose)

    if patch_result.already_patched:
        log_success("Library is already patched -- nothing to do")
        return

    if not patch_result.success:
        log_error(f"Patch failed: {patch_result.message}")
        log_warn("This driver version may not be supported by the binary patcher")
        log_warn("Do NOT use sed-based patching tools (regix1/nvidia-patch) as they")
        log_warn("corrupt ELF SONAME metadata and break container library mounting")
        return

    if dry_run:
        log_info(patch_result.message)
        return

    # ── Verify SONAME integrity after patching ─────────────────────
    soname_after = _verify_elf_soname(lib_path)
    if soname_before and not soname_after:
        log_error("CRITICAL: ELF SONAME was destroyed by patching!")
        log_error("Restoring from backup...")
        _restore_backup(driver_version, lib_path)
        log_error("Patch rolled back due to SONAME corruption")
        return

    if soname_after:
        log_success(f"ELF SONAME intact: {soname_after}")

    # Rebuild linker cache after successful patch
    run_command("ldconfig", check=False)

    # Verify ldconfig sees the library
    try:
        result = subprocess.run(
            "ldconfig -p | grep nvidia-encode",
            shell=True,
            capture_output=True,
            text=True,
        )
        if "libnvidia-encode" in result.stdout:
            log_success("ldconfig cache updated -- library is discoverable")
        else:
            log_warn("Library not found in ldconfig cache -- containers may not discover it")
            log_warn("Run: ldconfig && ldconfig -p | grep nvidia-encode")
    except OSError:
        pass

    log_success("NVENC session limit removed!")
    log_info(f"Backup: {_BACKUP_DIR}/libnvidia-encode.so.{driver_version}.orig")
    log_info("Rollback: re-run with rollback=True")
    log_warn("Restart any running NVENC applications / Docker containers.")


def _apply_nvfbc_patch() -> None:
    """Apply NvFBC patch for OBS / screen-capture support.

    Uses the upstream regix1/nvidia-patch script for NvFBC since we
    don't have a pure-Python patcher for it yet.

    WARNING: The upstream script uses sed-based binary patching which
    can corrupt ELF SONAME metadata. The NvFBC library (libnvidia-fbc.so)
    is less critical for container workflows than libnvidia-encode.so,
    but users should verify library integrity after patching.
    """
    log_warn("NvFBC patching uses upstream regix1/nvidia-patch (sed-based)")
    log_warn("This approach can corrupt ELF metadata -- verify library integrity afterward")

    _apply_upstream_nvfbc_script()


def _apply_upstream_nvfbc_script() -> None:
    """Clone regix1/nvidia-patch and run patch-fbc.sh.

    The upstream keylase scripts use nvidia-smi internally and do not
    accept a version override flag.  If nvidia-smi is broken (version
    mismatch after driver upgrade), we skip the upstream script and
    warn the user to reboot first.
    """
    if not _nvidia_smi_works():
        reboot_needed = _needs_reboot()
        if reboot_needed:
            log_warn(
                "Skipping upstream NvFBC patch: nvidia-smi reports "
                "driver/library version mismatch"
            )
            log_warn("Please reboot to load the new kernel module, then re-run this tool")
        else:
            log_warn("Skipping upstream NvFBC patch: nvidia-smi is not functional")
            log_warn("Please ensure NVIDIA drivers are properly installed and reboot if needed")
        return

    log_info("Applying NvFBC patch via upstream regix1/nvidia-patch...")

    with tempfile.TemporaryDirectory() as tmp:
        original_dir = os.getcwd()
        try:
            os.chdir(tmp)
            run_command("git clone https://github.com/regix1/nvidia-patch.git .")
            run_command("chmod +x patch-fbc.sh")
            run_command("bash ./patch-fbc.sh")
            log_success("NvFBC patch applied!")
            log_warn("Verify library integrity: readelf -d /usr/lib/x86_64-linux-gnu/libnvidia-fbc.so.* | grep SONAME")
        except subprocess.CalledProcessError as exc:
            log_warn(f"NvFBC patching failed: {exc}")
            log_warn("You can manually apply the patch later if needed")
        except OSError as exc:
            log_warn(f"NvFBC patching failed: {exc}")
            log_warn("You can manually apply the patch later if needed")
        finally:
            os.chdir(original_dir)

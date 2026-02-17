#!/usr/bin/env python3
"""NVIDIA Driver Setup - Thin wrapper for backwards compatibility.

Prefer using one of these instead:
  - nvidia-setup          (if installed via pip)
  - python3 -m nvidia_driver_setup
"""

from nvidia_driver_setup.cli import main

if __name__ == "__main__":
    main()

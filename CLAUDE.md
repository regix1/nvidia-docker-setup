# NVIDIA Driver Setup - Project Context

## What This Is
A pip-installable CLI tool (`nvidia-setup`) that automates NVIDIA driver installation,
Docker + NVIDIA Container Toolkit setup, CUDA version selection, driver patching
(NVENC session limit removal + NvFBC unlock), and media-server Docker configuration
on Ubuntu/Debian hosts.

## Architecture

```
nvidia_driver_setup/          # Python package (module name)
  __init__.py                 # __version__, __package_name__
  __main__.py                 # python3 -m nvidia_driver_setup entry
  cli.py                      # Main CLI: multi-select menu, execution ordering
  updater.py                  # Self-update (git pull or pip upgrade)
  nvidia/
    drivers.py                # Driver install + post-install cleanup
    cuda.py                   # CUDA version selection
    patches.py                # Binary patcher for NVENC + NvFBC
  docker/
    setup.py                  # Docker + NVIDIA runtime installation
    config.py                 # Docker compose config for media servers
  system/
    checks.py                 # Preliminary checks, full_nvidia_cleanup
  utils/
    logging.py                # Color log helpers (log_info, log_error, etc.)
    prompts.py                # prompt_yes_no, prompt_choice, prompt_multi_select
    system.py                 # run_command(), AptManager, cleanup functions
main.py                       # Thin wrapper for `python3 main.py` compat
setup.sh                      # Smart launcher: nvidia-setup -> python -m -> main.py
pyproject.toml                # Package metadata, console_scripts entry point
```

## Key Patterns

- **Root required**: `cli.py:main()` checks `os.geteuid() == 0` at startup.
- **Prompts**: Always use helpers from `utils/prompts.py` (`prompt_yes_no`, `prompt_multi_select`, etc.). Never raw `input()`.
- **Logging**: Use `utils/logging.py` functions (`log_info`, `log_warn`, `log_error`, `log_step`, `log_success`, `log_prompt`). Never bare `print()` for status messages.
- **Shell commands**: Use `run_command()` from `utils/system.py`. Never bare `os.system()` or `subprocess.run()` in feature code (except `updater.py` which manages its own subprocesses).
- **APT operations**: Use `AptManager` context manager from `utils/system.py`.
- **Imports**: Subpackages use relative imports (`from ..utils.logging import ...`). Entry points (`cli.py`, `__main__.py`) use absolute imports (`from nvidia_driver_setup.X`).

## Menu System
- Multi-select checkbox menu via `prompt_multi_select()`.
- `EXECUTION_ORDER` dict in `cli.py` controls run order (drivers first, self-update last).
- `build_menu_options()` returns parallel `(options, descriptions, statuses)` lists.
- `execute_selected_items()` sorts by priority, dispatches via `_execute_single_item()`.

## Self-Update (`updater.py`)
- Detects install method: git clone (`.git` dir present) vs pip.
- Git: `git fetch` + `git pull origin main` + `pip install -e .`
- Pip: `pip index versions` + `pip install --upgrade nvidia-driver-setup`
- Always runs last in execution order; Python keeps old code in memory.

## Testing Commands
```bash
python3 -c "from nvidia_driver_setup.updater import run_self_update; print('OK')"
python3 -c "from nvidia_driver_setup.utils.prompts import prompt_multi_select; print('OK')"
python3 -c "from nvidia_driver_setup.cli import main; print('OK')"
sudo nvidia-setup    # Full interactive test
```

## Critical Constraints
- Must run as root (sudo) on Linux hosts.
- NVENC patch uses binary scanning with multiple anchor patterns - never hardcode offsets.
- WSL NVIDIA libraries differ from Linux host - don't cross-reference.
- `setup.sh` is the recommended entry point for first-time users without pip install.

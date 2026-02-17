"""Logging utilities for NVIDIA Driver Setup"""


class Colors:
    """ANSI color codes for terminal output"""
    RESET = '\033[0m'
    BOLD = '\033[1m'
    RED = '\033[1;31m'
    GREEN = '\033[1;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[1;34m'
    CYAN = '\033[1;36m'


def log_info(message):
    """Log info message in green"""
    print(f"{Colors.GREEN}[INFO]  {message}{Colors.RESET}")


def log_warn(message):
    """Log warning message in yellow"""
    print(f"{Colors.YELLOW}[WARN]  {message}{Colors.RESET}")


def log_error(message):
    """Log error message in red"""
    print(f"{Colors.RED}[ERROR] {message}{Colors.RESET}")


def log_prompt(message):
    """Log prompt message in cyan"""
    print(f"{Colors.CYAN}[INPUT] {message}{Colors.RESET}", end='')


def log_step(message):
    """Log step message in blue with newline before"""
    print(f"\n{Colors.BLUE}[STEP]  {message}{Colors.RESET}")


def log_success(message):
    """Log success message in bold green"""
    print(f"{Colors.BOLD}{Colors.GREEN}✓ {message}{Colors.RESET}")
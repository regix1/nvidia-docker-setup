"""Interactive prompt utilities"""

import sys

from .logging import log_prompt, log_error, log_info


def prompt_yes_no(prompt, default='y'):
    """
    Interactive yes/no prompt

    Args:
        prompt: Question to ask
        default: Default answer ('y' or 'n')

    Returns:
        bool: True for yes, False for no
    """
    while True:
        log_prompt(f"{prompt} [Y/n]: ")
        response = input().strip()
        response = response or default

        if response.lower() in ['y', 'yes']:
            return True
        elif response.lower() in ['n', 'no']:
            return False
        else:
            log_error("Please answer yes or no.")


def prompt_choice(prompt, choices, default=None):
    """
    Interactive multiple choice prompt

    Args:
        prompt: Question to ask
        choices: List of choices
        default: Default choice index (0-based)

    Returns:
        int: Index of selected choice
    """
    while True:
        if default is not None:
            log_prompt(f"{prompt} [1-{len(choices)}, default: {default + 1}]: ")
        else:
            log_prompt(f"{prompt} [1-{len(choices)}]: ")

        response = input().strip()

        if not response and default is not None:
            return default

        try:
            choice_num = int(response)
            if 1 <= choice_num <= len(choices):
                return choice_num - 1
            else:
                log_error(f"Please enter a number between 1 and {len(choices)}")
        except ValueError:
            log_error("Please enter a valid number")


def prompt_input(prompt, default=None, required=True):
    """
    Interactive input prompt

    Args:
        prompt: Question to ask
        default: Default value
        required: Whether input is required

    Returns:
        str: User input or default
    """
    while True:
        default_text = f" (default: {default})" if default else ""
        log_prompt(f"{prompt}{default_text}: ")
        response = input().strip()

        if response:
            return response
        elif default is not None:
            return default
        elif not required:
            return ""
        else:
            log_error("This field is required")


def prompt_acknowledge(message, required_response):
    """
    Force user to type specific text to acknowledge

    Args:
        message: Message to display
        required_response: Exact text user must type
    """
    print(f"\n{message}\n")

    while True:
        log_prompt(f"Type '{required_response}' to acknowledge: ")
        response = input().strip()

        if response == required_response:
            break
        else:
            log_error(f"Please type '{required_response}' to continue")


def _curses_multi_select(
    prompt: str,
    options: list[str],
    descriptions: list[str],
    statuses: list[str],
    pre_selected: set[int] | None = None,
    exit_label: str = "Exit",
) -> list[int]:
    """Curses-based interactive multi-select with arrow keys.

    Up/Down or j/k to move, Space to toggle, 'a' to toggle all,
    Enter to execute selected, 'q' or Esc to exit.
    """
    import curses

    selected: set[int] = set(pre_selected) if pre_selected else set()
    cursor = 0  # 0 = Exit, 1..N = options
    total_items = len(options) + 1  # +1 for Exit row

    def _draw(stdscr: "curses.window") -> list[int]:
        nonlocal cursor, selected
        curses.curs_set(0)
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)     # highlight
        curses.init_pair(2, curses.COLOR_GREEN, -1)     # selected / OK
        curses.init_pair(3, curses.COLOR_YELLOW, -1)    # status tags
        curses.init_pair(4, curses.COLOR_WHITE, -1)     # normal
        curses.init_pair(5, curses.COLOR_RED, -1)       # not installed

        while True:
            stdscr.clear()
            max_y, max_x = stdscr.getmaxyx()

            # Header
            stdscr.addnstr(0, 0, prompt, max_x - 1, curses.A_BOLD)

            row = 2
            # Exit option
            prefix = " > " if cursor == 0 else "   "
            attr = curses.color_pair(1) | curses.A_BOLD if cursor == 0 else curses.color_pair(4)
            exit_text = f"{prefix}0. {exit_label}"
            if row < max_y:
                stdscr.addnstr(row, 0, exit_text, max_x - 1, attr)
            row += 1

            # Menu items
            for idx, (opt, desc, status) in enumerate(zip(options, descriptions, statuses)):
                if row + 1 >= max_y:
                    break
                is_cursor = (cursor == idx + 1)
                marker = "*" if idx in selected else " "

                # Build the line
                prefix = " > " if is_cursor else "   "
                line = f"{prefix}[{marker}] {idx + 1}. {opt}"
                if status:
                    line += f" {status}"

                if is_cursor:
                    attr = curses.color_pair(1) | curses.A_BOLD
                elif idx in selected:
                    attr = curses.color_pair(2)
                else:
                    attr = curses.color_pair(4)

                stdscr.addnstr(row, 0, line, max_x - 1, attr)
                row += 1

                # Description line
                desc_line = f"       {desc}"
                desc_attr = curses.color_pair(1) if is_cursor else curses.color_pair(4) | curses.A_DIM
                if row < max_y:
                    stdscr.addnstr(row, 0, desc_line, max_x - 1, desc_attr)
                row += 1

            # Footer
            row += 1
            count = len(selected)
            if row < max_y:
                footer = f" {count} selected  |  Space: toggle  a: all  Enter: run  q: exit"
                stdscr.addnstr(row, 0, footer, max_x - 1, curses.color_pair(3))

            stdscr.refresh()

            # Input
            key = stdscr.getch()

            if key == curses.KEY_UP or key == ord('k'):
                cursor = (cursor - 1) % total_items
            elif key == curses.KEY_DOWN or key == ord('j'):
                cursor = (cursor + 1) % total_items
            elif key == ord(' '):
                if cursor == 0:
                    # Space on Exit = exit
                    return []
                idx = cursor - 1
                if idx in selected:
                    selected.discard(idx)
                else:
                    selected.add(idx)
            elif key == ord('a'):
                if len(selected) == len(options):
                    selected.clear()
                else:
                    selected = set(range(len(options)))
            elif key in (curses.KEY_ENTER, 10, 13):
                if cursor == 0:
                    return []
                if not selected:
                    # Nothing selected, don't proceed
                    continue
                return sorted(selected)
            elif key in (ord('q'), 27):  # q or Esc
                return []

    return curses.wrapper(_draw)


def _fallback_multi_select(
    prompt: str,
    options: list[str],
    descriptions: list[str],
    statuses: list[str],
    pre_selected: set[int] | None = None,
    exit_label: str = "Exit",
) -> list[int]:
    """Number-based fallback multi-select for terminals without curses."""
    selected: set[int] = set(pre_selected) if pre_selected else set()

    def _render() -> None:
        print(f"\n{prompt}")
        print(f"  0. {exit_label}")
        for idx, (opt, desc, status) in enumerate(zip(options, descriptions, statuses)):
            marker = "*" if idx in selected else " "
            status_tag = f" {status}" if status else ""
            print(f"  [{marker}] {idx + 1}. {opt}{status_tag}")
            print(f"          {desc}")
        count = len(selected)
        print()
        log_info(f"{count} item(s) selected.  "
                 "Enter numbers to toggle | 'a' = toggle all | Enter = run selected | 0 = exit")

    while True:
        _render()
        log_prompt(">> ")
        raw = input().strip()

        if raw == "":
            if not selected:
                log_error("Nothing selected. Pick items or press 0 to exit.")
                continue
            return sorted(selected)

        if raw == "0":
            return []

        if raw.lower() == "a":
            if len(selected) == len(options):
                selected.clear()
            else:
                selected = set(range(len(options)))
            continue

        tokens = raw.replace(",", " ").split()
        valid = True
        for token in tokens:
            try:
                num = int(token)
            except ValueError:
                log_error(f"Invalid input: '{token}'")
                valid = False
                break
            if num == 0:
                return []
            if num < 1 or num > len(options):
                log_error(f"Out of range: {num} (valid: 1-{len(options)})")
                valid = False
                break
            idx = num - 1
            if idx in selected:
                selected.discard(idx)
            else:
                selected.add(idx)
        if not valid:
            continue


def prompt_multi_select(
    prompt: str,
    options: list[str],
    descriptions: list[str],
    statuses: list[str],
    pre_selected: set[int] | None = None,
    exit_label: str = "Exit",
) -> list[int]:
    """Multi-select checkbox menu.

    Uses curses for interactive arrow-key navigation when available,
    falls back to number-based input otherwise.

    Args:
        prompt: Header text shown above the menu.
        options: Display labels for each option.
        descriptions: One-line description per option.
        statuses: Short status tag per option (e.g. "[OK]", "[--]").
        pre_selected: Indices to pre-select (0-based). None means empty set.
        exit_label: Label for the exit/cancel action (item 0).

    Returns:
        Sorted list of selected 0-based indices. Empty list means exit/cancel.
    """
    # Try curses for interactive menu, fall back to number input
    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            return _curses_multi_select(
                prompt, options, descriptions, statuses, pre_selected, exit_label
            )
        except Exception as exc:
            print(
                f"\033[1;33m[WARN]  Interactive menu unavailable "
                f"({type(exc).__name__}: {exc}), using text menu\033[0m",
                file=sys.stderr,
            )

    return _fallback_multi_select(
        prompt, options, descriptions, statuses, pre_selected, exit_label
    )

"""Interactive prompt utilities"""

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


def prompt_multi_select(
    prompt: str,
    options: list[str],
    descriptions: list[str],
    statuses: list[str],
    pre_selected: set[int] | None = None,
    exit_label: str = "Exit",
) -> list[int]:
    """Multi-select checkbox menu.

    Shows numbered options with [*]/[ ] checkboxes. The user can toggle items
    by entering space-separated numbers, 'a' to toggle all, Enter to run
    selected items, or '0' to exit.

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

        # Enter with no input -> run selected
        if raw == "":
            if not selected:
                log_error("Nothing selected. Pick items or press 0 to exit.")
                continue
            return sorted(selected)

        # Exit
        if raw == "0":
            return []

        # Toggle all
        if raw.lower() == "a":
            if len(selected) == len(options):
                selected.clear()
            else:
                selected = set(range(len(options)))
            continue

        # Parse space-separated numbers
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
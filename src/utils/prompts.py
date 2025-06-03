"""Interactive prompt utilities"""

from .logging import log_prompt, log_error


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
    print(f"\n{prompt}")
    for i, choice in enumerate(choices, 1):
        marker = " (default)" if default is not None and i-1 == default else ""
        print(f"  {i}. {choice}{marker}")
    
    while True:
        log_prompt(f"Enter your choice [1-{len(choices)}]: ")
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
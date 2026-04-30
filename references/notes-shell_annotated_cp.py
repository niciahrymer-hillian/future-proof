#!/usr/bin/env python3
"""Annotated reference copy of the starter notes shell.

This scaffold intentionally stays small so learners can see the
control flow from startup -> command loop -> shutdown.
"""

import sys
from pathlib import Path


# [SETUP] Print startup information and resolve the notes folder path.
# Effect: gives a clear first-run message even when the folder is missing.
def setup():
    """Initialize the notes application."""
    print("Future Proof Notes Manager v0.0")
    print("=" * 40)

    # [PATH] Starter shell checks only ~/.notes (top-level folder).
    notes_dir = Path.home() / ".notes"

    if not notes_dir.exists():
        print(f"Notes directory not found at {notes_dir}")
        print("Run 'notes init' to create it.")
    else:
        print(f"Notes directory: {notes_dir}")

    print()
    return notes_dir


# [HELP] Central place for command list display.
def show_help():
    """Display help information."""
    help_text = """
Available commands:
  help    - Display this help information
  quit    - Exit the application
    """
    print(help_text)


# [LOOP] Read-eval-print style loop for interactive command handling.
# Effect: keeps accepting commands until user quits or sends EOF.
def command_loop():
    """Main command loop for processing user input."""
    while True:
        try:
            command = input("notes> ").strip().lower()

            if not command:
                continue

            if command == "quit":
                break
            elif command == "help":
                show_help()
            else:
                print(f"Unknown command: '{command}'")
                print("Type 'help' for available commands.")

        except EOFError:
            # Ctrl+D closes stdin; treat as a normal exit.
            print()
            break
        except KeyboardInterrupt:
            # Ctrl+C keeps session alive and reminds user of normal quit path.
            print("\nUse 'quit' to exit.")


# [FINISH] Single exit path for friendly shutdown message.
def finish():
    """Clean up and exit the application."""
    print("\nGoodbye!")
    sys.exit(0)


# [MAIN] Program orchestration entrypoint.
def main():
    """Main entry point for the notes application."""
    setup()
    command_loop()
    finish()


if __name__ == "__main__":
    main()

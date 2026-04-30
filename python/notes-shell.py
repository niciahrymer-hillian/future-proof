#!/usr/bin/env python3
"""
Future Proof Notes Manager - Version Zero
A personal notes manager using text files with YAML headers.
"""

import os
import sys
from pathlib import Path


def setup():
    """Initialize the notes application."""
    print("Future Proof Notes Manager v0.0")
    print("=" * 40)

    # This starter shell checks only the top-level ~/.notes folder.
    notes_dir = Path.home() / ".notes"

    # Check if notes directory exists
    if not notes_dir.exists():
        print(f"Notes directory not found at {notes_dir}")
        print("Run 'notes init' to create it.")
    else:
        print(f"Notes directory: {notes_dir}")

    print()
    return notes_dir


def show_help():
    """Display help information."""
    help_text = """
Available commands:
  help    - Display this help information
  quit    - Exit the application
    """
    print(help_text)


def command_loop():
    """Main command loop for processing user input."""
    while True:
        try:
            # Read one command at a time from the prompt.
            command = input("notes> ").strip().lower()

            # Handle empty input
            if not command:
                continue

            # Minimal command router for this learning stage.
            if command == "quit":
                break
            elif command == "help":
                show_help()
            else:
                print(f"Unknown command: '{command}'")
                print("Type 'help' for available commands.")

        except EOFError:
            # Ctrl+D closes stdin; treat it as normal exit.
            print()
            break
        except KeyboardInterrupt:
            # Ctrl+C keeps the app open and reminds how to quit cleanly.
            print("\nUse 'quit' to exit.")


def finish():
    """Clean up and exit the application."""
    print("\nGoodbye!")
    sys.exit(0)


def main():
    """Main entry point for the notes application."""
    # Setup prints startup info and returns the notes folder path.
    notes_dir = setup()

    # Command loop
    command_loop()

    # Finish
    finish()


if __name__ == "__main__":
    main()

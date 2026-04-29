#!/usr/bin/env python3
"""
Future Proof Notes Manager - Version Zero (CLI)
A personal notes manager using text files with YAML headers.
Command-line interface version.
"""

import sys
from datetime import datetime
from pathlib import Path

# Single source of truth for the notes directory in the users home folder 
NOTES_DIR = Path.home() / ".notes" / "notes"


def setup():
    """Initialize the notes application."""
    return NOTES_DIR


def init_notes(notes_dir):
    """Create the notes directory if it does not exist."""
    notes_dir.mkdir(parents=True, exist_ok=True)
    print(f"Notes directory ready: {notes_dir}")


def _slugify(text):
    """Create a simple filename-safe slug from title text."""
    return "-".join(text.strip().lower().split())


def create_note(notes_dir, title, content):
    """Create a note with YAML frontmatter and body content."""
    if not title.strip():
        raise ValueError("title cannot be empty")
    if not content.strip():
        raise ValueError("content cannot be empty")

    init_notes(notes_dir)

    timestamp = datetime.now()
    note_id = f"{timestamp.strftime('%Y%m%d-%H%M%S')}-{_slugify(title)}"
    note_path = notes_dir / f"{note_id}.note"

    note_text = (
        "---\n"
        f"title: {title}\n"
        f"created: {timestamp.isoformat(timespec='seconds')}\n"
        "---\n\n"
        f"{content.strip()}\n"
    )
    note_path.write_text(note_text, encoding="utf-8")
    print(f"Created note: {note_path}")

def list_notes():
    if

def read_note():

def delete_note():

def search_notes():

def help_command():

def update_note():

def show_help():
    """Display help information."""
    # Current behavior: provide minimal CLI help for phase-0 scaffolding.
    # Instructor likely wants: command discovery and predictable CLI UX.
    help_text = """
Future Proof Notes Manager v0.0

Usage: notes0.py [command]

Available commands:
    init    - Create the notes directory if missing
    create  - Create a note (title and content)
  help    - Display this help information

Notes directory: {}
    """.format(NOTES_DIR)
    print(help_text.strip())




def finish(exit_code=0):
    """Clean up and exit the application."""
    # Current behavior: centralize process exit in one function.
    # Instructor likely wants: one place to control exit behavior across commands.
    sys.exit(exit_code)


def main():
    """Main entry point for the notes CLI application."""
    # Setup
    notes_dir = setup()

    # Parse command-line arguments
    if len(sys.argv) < 2:
        # No command provided
        print("Error: No command provided.", file=sys.stderr)
        print("Usage: notes0.py [command]", file=sys.stderr)
        print("Try 'notes0.py help' for more information.", file=sys.stderr)
        finish(1)

    command = sys.argv[1].lower()

    if command == "help":
        show_help()
        finish(0)
    elif command == "init":
        init_notes(notes_dir)
        finish(0)
    elif command == "create":
        if len(sys.argv) >= 4:
            title = sys.argv[2]
            content = " ".join(sys.argv[3:])
        else:
            title = input("Title: ").strip()
            content = input("Content: ").strip()

        try:
            create_note(notes_dir, title, content)
            finish(0)
        except ValueError as err:
            print(f"Error: {err}", file=sys.stderr)
            finish(1)
    else:
        print(f"Error: Unknown command '{command}'", file=sys.stderr)
        print("Try 'notes0.py help' for more information.", file=sys.stderr)
        finish(1)


if __name__ == "__main__":
    main()

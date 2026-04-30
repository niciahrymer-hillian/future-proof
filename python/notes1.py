#!/usr/bin/env python3
"""
Future Proof Notes Manager - Version One (CLI)
A personal notes manager using text files with YAML headers.
Command-line interface version with 'list' command.

SETUP REMINDER:
Before running the 'list' command, copy the test notes to your notes directory:
    cp -r test-notes/* ~/.notes/
or create the directory structure:
    mkdir -p ~/.notes/notes
    cp test-notes/*.md ~/.notes/notes/
"""

import sys
from pathlib import Path


def setup():
    """Initialize the notes application."""
    # Version 1 uses ~/.notes as root and looks for optional ~/.notes/notes.
    notes_dir = Path.home() / ".notes"

    # Starter behavior: report/handle later instead of auto-creating.
    if not notes_dir.exists():
        # For CLI version, we don't automatically create it
        pass

    return notes_dir


def parse_yaml_header(file_path):
    """
    Parse YAML front matter from a note file.
    Returns a dictionary with metadata and the content.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Frontmatter must start with --- on the first line.
        if not lines or lines[0].strip() != '---':
            return {'title': file_path.name, 'file': file_path.name}

        # Find matching closing marker for the metadata block.
        yaml_end = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == '---':
                yaml_end = i
                break

        if yaml_end == -1:
            return {'title': file_path.name, 'file': file_path.name}

        # Lightweight parser: handles basic key: value pairs only.
        metadata = {'file': file_path.name}
        for line in lines[1:yaml_end]:
            line = line.strip()
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()
                metadata[key] = value

        return metadata

    except Exception as e:
        return {'title': file_path.name, 'file': file_path.name, 'error': str(e)}


def list_notes(notes_dir):
    """List all notes in the notes directory."""
    # Fail early with a setup hint when folder is missing.
    if not notes_dir.exists():
        print(f"Error: Notes directory does not exist: {notes_dir}", file=sys.stderr)
        print("Create it with: mkdir -p ~/.notes/notes", file=sys.stderr)
        print("Then copy test notes: cp test-notes/*.md ~/.notes/notes/", file=sys.stderr)
        return False

    # Prefer ~/.notes/notes if present, otherwise fall back to ~/.notes.
    notes_subdir = notes_dir / "notes"
    search_dirs = [notes_subdir] if notes_subdir.exists() else [notes_dir]

    # Accept common text note extensions.
    note_files = []
    for search_dir in search_dirs:
        note_files.extend(search_dir.glob("*.md"))
        note_files.extend(search_dir.glob("*.note"))
        note_files.extend(search_dir.glob("*.txt"))

    if not note_files:
        print(f"No notes found in {notes_dir}")
        print("Copy test notes with: cp test-notes/*.md ~/.notes/", file=sys.stderr)
        return True

    # Parse metadata and print a readable summary list.
    print(f"Notes in {notes_dir}:")
    print("=" * 60)

    for note_file in sorted(note_files):
        metadata = parse_yaml_header(note_file)
        title = metadata.get('title', note_file.name)
        created = metadata.get('created', 'N/A')
        tags = metadata.get('tags', '')

        print(f"\n{note_file.name}")
        print(f"  Title: {title}")
        if created != 'N/A':
            print(f"  Created: {created}")
        if tags:
            print(f"  Tags: {tags}")

    print(f"\n{len(note_files)} note(s) found.")
    return True


def show_help():
    """Display help information."""
    help_text = """
Future Proof Notes Manager v0.1

Usage: notes1.py [command]

Available commands:
  help    - Display this help information
  list    - List all notes in the notes directory

Notes directory: {}

Setup:
  To test the 'list' command, copy sample notes:
    mkdir -p ~/.notes/notes
    cp test-notes/*.md ~/.notes/notes/
    """.format(Path.home() / ".notes")
    print(help_text.strip())


def finish(exit_code=0):
    """Clean up and exit the application."""
    sys.exit(exit_code)


def main():
    """Main entry point for the notes CLI application."""
    # Setup returns folder path used by list command.
    notes_dir = setup()

    # This version runs only in command-line argument mode.
    if len(sys.argv) < 2:
        # No command provided
        print("Error: No command provided.", file=sys.stderr)
        print("Usage: notes1.py [command]", file=sys.stderr)
        print("Try 'notes1.py help' for more information.", file=sys.stderr)
        finish(1)

    command = sys.argv[1].lower()

    # Command router: help and list are supported in version 1.
    if command == "help":
        show_help()
        finish(0)
    elif command == "list":
        success = list_notes(notes_dir)
        finish(0 if success else 1)
    else:
        print(f"Error: Unknown command '{command}'", file=sys.stderr)
        print("Try 'notes1.py help' for more information.", file=sys.stderr)
        finish(1)


if __name__ == "__main__":
    main()

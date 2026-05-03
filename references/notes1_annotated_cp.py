#!/usr/bin/env python3
"""
Future Proof Notes Manager - Version One (CLI) — Reference Copy

[ANATOMY]
A personal notes manager using text files with YAML headers.
Command-line interface version with 'list' command (and 'help').
This is an intermediate CLI between the very first notes0 version and the full API.

[WHY NOTES1 EXISTS]
Notes0 is the full-featured reference implementation (notes0.py ~874 lines).
Notes1 is a teaching version that shows a minimal, beginner-friendly CLI.
It demonstrates:
- Basic YAML header parsing (lightweight, no external deps)
- Directory setup and error handling
- Simple command router (help, list)
- Safe error messages for setup failures
- How a CLI evolves from "help text" to "working list command"

[PATTERN]
Version1 → Version2 (tests) → Version3 (refactored) → API layer (notes_api.py)
This file represents the "first working CLI with list command" milestone.
"""

import sys
from pathlib import Path


def setup():
    """
    [EFFECT]
    Initialize the notes application by returning the notes directory path.
    In version 1, we don't auto-create the folder — we just return the path.
    Caller is responsible for checking existence (list_notes() does this).
    
    [WHY NO AUTO-CREATE]
    Version 1 is passive: it reports what it finds and guides the user to fix problems.
    Later versions (notes0.py) will be more proactive (auto-create, error handling).
    """
    # Version 1 uses ~/.notes as root and looks for optional ~/.notes/notes.
    notes_dir = Path.home() / ".notes"

    # Starter behavior: report/handle later instead of auto-creating.
    if not notes_dir.exists():
        # For CLI version, we don't automatically create it
        pass

    return notes_dir


def parse_yaml_header(file_path):
    """
    [EFFECT]
    Parse YAML front matter from a note file.
    Returns a dictionary with metadata and the content.
    
    [WHY LIGHTWEIGHT]
    No pyyaml dependency — just split on ':' and handle basic key: value pairs.
    This is "good enough" for a v1 CLI and shows how simple YAML parsing can be.
    
    [PATTERN]
    Later versions (notes0.py) use more robust parsing and validation.
    But for v1, simple is the goal.
    
    [PARAMETER] file_path: Path object or string to a note file.
    [RETURN] dict with 'title', 'created', 'tags', 'file' keys (if present in metadata).
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # [RULE] Frontmatter must start with --- on the first line.
        if not lines or lines[0].strip() != '---':
            return {'title': file_path.name, 'file': file_path.name}

        # [RULE] Find matching closing marker for the metadata block.
        yaml_end = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == '---':
                yaml_end = i
                break

        if yaml_end == -1:
            return {'title': file_path.name, 'file': file_path.name}

        # [PATTERN] Lightweight parser: handles basic key: value pairs only.
        # Lines between --- and --- are split on first ':' character.
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
        # [ERROR HANDLING] On read failure, return a safe default with error note.
        return {'title': file_path.name, 'file': file_path.name, 'error': str(e)}


def list_notes(notes_dir):
    """
    [EFFECT]
    List all notes in the notes directory and print a readable summary.
    Returns True on success, False if setup is needed.
    
    [WHY EARLY FAIL]
    If notes directory doesn't exist, we print a clear error and setup hint.
    This helps new users understand what went wrong and how to fix it.
    
    [PARAMETER] notes_dir: Path object pointing to ~/.notes
    [RETURN] bool: True if listing succeeded or folder is empty but valid, False if folder missing.
    """
    # Fail early with a setup hint when folder is missing.
    if not notes_dir.exists():
        print(f"Error: Notes directory does not exist: {notes_dir}", file=sys.stderr)
        print("Create it with: mkdir -p ~/.notes/notes", file=sys.stderr)
        print("Then copy test notes: cp test-notes/*.md ~/.notes/notes/", file=sys.stderr)
        return False

    # [PATTERN] Prefer ~/.notes/notes if present, otherwise fall back to ~/.notes.
    # This gives users a chance to organize notes in a subdirectory.
    notes_subdir = notes_dir / "notes"
    search_dirs = [notes_subdir] if notes_subdir.exists() else [notes_dir]

    # [RULE] Accept common text note extensions: .md, .note, .txt
    note_files = []
    for search_dir in search_dirs:
        note_files.extend(search_dir.glob("*.md"))
        note_files.extend(search_dir.glob("*.note"))
        note_files.extend(search_dir.glob("*.txt"))

    if not note_files:
        print(f"No notes found in {notes_dir}")
        print("Copy test notes with: cp test-notes/*.md ~/.notes/", file=sys.stderr)
        return True

    # [DISPLAY] Parse metadata and print a readable summary list.
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
    """
    [EFFECT]
    Display help information to stdout.
    Explains available commands and setup instructions.
    """
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
    """
    [EFFECT]
    Clean up and exit the application.
    
    [WHY HELPER]
    Centralizes exit logic. In v1 this is simple sys.exit(),
    but later versions might add cleanup (file handles, temp dirs, etc.).
    """
    sys.exit(exit_code)


def main():
    """
    [EFFECT]
    Main entry point for the notes CLI application.
    Routes command-line arguments to appropriate functions.
    
    [PATTERN]
    1. Call setup() to get notes directory path
    2. Check for command-line argument (sys.argv[1])
    3. Route to appropriate function (help, list, or error)
    4. Exit with appropriate code
    """
    # [STEP 1] Setup returns folder path used by list command.
    notes_dir = setup()

    # [STEP 2] This version runs only in command-line argument mode.
    # (No interactive menu like notes0.py)
    if len(sys.argv) < 2:
        # No command provided
        print("Error: No command provided.", file=sys.stderr)
        print("Usage: notes1.py [command]", file=sys.stderr)
        print("Try 'notes1.py help' for more information.", file=sys.stderr)
        finish(1)

    command = sys.argv[1].lower()

    # [STEP 3] Command router: help and list are supported in version 1.
    # (Version 0 has more commands; version 2+ adds more features)
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

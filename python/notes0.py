#!/usr/bin/env python3
"""
Future Proof Notes Manager - Version Zero (CLI)
A personal notes manager using text files with YAML headers.
Command-line interface version.
"""

import sys
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import yaml
from config import DEFAULT_EDITOR, NOTE_EXTENSION, NOTES_DIR, PREVIEW_CHARS

# Single source of truth for the notes directory now lives in config.py


def ensure_notes_dir(notes_dir=NOTES_DIR):
    """Ensure notes directory exists with private permissions (0700)."""
    try:
        # Create the folder tree if missing; no error if it already exists.
        notes_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Re-apply private permissions each run so the directory stays locked down.
        notes_dir.chmod(0o700)
        return notes_dir
    except OSError as err:
        raise RuntimeError(
            f"Could not prepare notes directory at {notes_dir}. "
            "Please check directory permissions."
        ) from err


def setup():
    """Initialize the notes application."""
    return ensure_notes_dir(NOTES_DIR)


def init_notes(notes_dir):
    """Create the notes directory if it does not exist."""
    ensure_notes_dir(notes_dir)
    print(f"Notes directory ready: {notes_dir}")


def _slugify(text):
    """Create a simple filename-safe slug from title text."""
    # Keep letters/digits, turn everything else into dashes.
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in text.strip())
    # Remove empty chunks caused by repeated separators.
    parts = [part for part in cleaned.split("-") if part]
    return "-".join(parts) or "untitled"


def _generate_note_id(notes_dir, timestamp, title=""):
    """Generate sortable note id and add -2/-3 suffixes on collisions."""
    # Date first makes IDs naturally sort by creation time.
    slug = _slugify(title)[:30] if title else "untitled"
    base_id = f"note_{timestamp.strftime('%Y%m%d_%H%M%S')}_{slug}"

    # If the ID already exists, append numeric suffixes.
    note_id = base_id
    suffix = 2
    while (notes_dir / f"{note_id}{NOTE_EXTENSION}").exists():
        note_id = f"{base_id}-{suffix}"
        suffix += 1
    return note_id


@dataclass
class Note:
    """Note model for metadata + content."""

    id: str
    title: str
    author: str
    created: str
    modified: str
    tags: list[str] = field(default_factory=list)
    status: str = "draft"
    priority: int = 3
    content: str = ""
    extra_metadata: dict = field(default_factory=dict)

    def validate(self):
        """Validate required fields and limits."""
        # Required metadata from the spec.
        if not self.title or not self.title.strip():
            raise ValueError("title is required")
        if not self.author or not self.author.strip():
            raise ValueError("author is required")
        # Priority scale is intentionally small and bounded.
        if not isinstance(self.priority, int) or not (1 <= self.priority <= 5):
            raise ValueError("priority must be between 1 and 5")
        return self

    def to_text(self):
        """Render note as YAML frontmatter + body text."""
        return serialize_note(self)


def parse_note(text):
    """Parse YAML frontmatter + body into a Note model."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("Invalid note format: missing YAML frontmatter at line 1")

    yaml_end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            yaml_end = i
            break
    if yaml_end == -1:
        raise ValueError("Invalid note format: missing closing '---' for YAML frontmatter")

    yaml_text = "\n".join(lines[1:yaml_end])
    body = "\n".join(lines[yaml_end + 1:]).strip()

    try:
        metadata = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as err:
        mark = getattr(err, "problem_mark", None)
        line_no = (mark.line + 2) if mark is not None else 2
        problem = getattr(err, "problem", str(err))
        raise ValueError(f"Invalid YAML frontmatter at line {line_no}: {problem}") from err

    if not isinstance(metadata, dict):
        raise ValueError("Invalid YAML frontmatter at line 2: expected key/value mapping")

    priority_raw = metadata.get("priority", 3)
    try:
        priority = int(priority_raw)
    except (TypeError, ValueError) as err:
        raise ValueError("Invalid YAML frontmatter at line 2: priority must be an integer") from err

    tags_raw = metadata.get("tags", [])
    if isinstance(tags_raw, list):
        tags = [str(tag).strip() for tag in tags_raw if str(tag).strip()]
    elif isinstance(tags_raw, str):
        tags = [tag.strip() for tag in tags_raw.split(",") if tag.strip()]
    else:
        raise ValueError("Invalid YAML frontmatter at line 2: tags must be a list or string")

    known_fields = {"id", "title", "author", "created", "modified", "tags", "status", "priority"}
    extra_metadata = {k: v for k, v in metadata.items() if k not in known_fields}

    note = Note(
        id=str(metadata.get("id", "")).strip(),
        title=str(metadata.get("title", "")).strip(),
        author=str(metadata.get("author", "")).strip(),
        created=str(metadata.get("created", "")).strip(),
        modified=str(metadata.get("modified", "")).strip(),
        tags=tags,
        status=str(metadata.get("status", "draft")).strip() or "draft",
        priority=priority,
        content=body,
        extra_metadata=extra_metadata,
    )
    return note.validate()


def serialize_note(note):
    """Serialize a Note model into YAML frontmatter + body text."""
    note.validate()

    metadata = {}
    if note.id:
        metadata["id"] = note.id
    metadata["title"] = note.title
    metadata["author"] = note.author
    if note.created:
        metadata["created"] = note.created
    if note.modified:
        metadata["modified"] = note.modified
    metadata["tags"] = note.tags
    metadata["status"] = note.status
    metadata["priority"] = note.priority

    for key, value in note.extra_metadata.items():
        if key not in metadata:
            metadata[key] = value

    yaml_text = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{yaml_text}\n---\n\n{note.content.strip()}\n"


def _atomic_write_text(target_path, text):
    """Write text atomically using temp file + rename."""
    ensure_notes_dir(target_path.parent)
    tmp_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=target_path.parent,
            prefix=".tmp-note-",
            suffix=target_path.suffix,
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            tmp_file = Path(handle.name)
        os.replace(tmp_file, target_path)
    finally:
        if tmp_file and tmp_file.exists():
            tmp_file.unlink(missing_ok=True)


def create_note(notes_dir, title, content):
    """Create a note with YAML frontmatter and body content."""
    # Input validation happens early so we fail fast.
    if not title.strip():
        raise ValueError("title cannot be empty")
    if not content.strip():
        raise ValueError("content cannot be empty")

    # Any command should be safe even when folders do not exist yet.
    init_notes(notes_dir)

    timestamp = datetime.now()
    # Default author comes from OS user when available.
    author = os.getenv("USER", "").strip() or "unknown"
    # Build and validate one model object before writing anything to disk.
    note = Note(
        id=_generate_note_id(notes_dir, timestamp, title),
        title=title.strip(),
        author=author,
        created=timestamp.isoformat(timespec="seconds"),
        modified=timestamp.isoformat(timespec="seconds"),
        tags=[],
        status="draft",
        priority=3,
        content=content.strip(),
    ).validate()

    # File name and frontmatter share the same ID.
    note_path = notes_dir / f"{note.id}{NOTE_EXTENSION}"
    _atomic_write_text(note_path, note.to_text())
    print(f"Created note: {note_path}")
    return note.id

def list_notes():
    """Return a list of note metadata (id, title, created) for all notes in the directory."""
    notes = []
    for note_file in NOTES_DIR.glob(f"*{NOTE_EXTENSION}"):
        try:
            note_text = note_file.read_text(encoding="utf-8")
            note = parse_note(note_text)
        except (OSError, UnicodeDecodeError, ValueError) as err:
            print(f"Skipping bad note '{note_file.name}': {err}")
            continue

        preview = note.content.replace("\n", " ")[:PREVIEW_CHARS]
        notes.append({
            "id": note.id or note_file.name[: -len(NOTE_EXTENSION)],
            "title": note.title,
            "created": note.created,
            "modified": note.modified,
            # C5: tags included so print_notes_list() can display them.
            "tags": note.tags,
            "preview": preview
        })

    def sort_key(item):
        stamp = item.get("modified") or item.get("created") or ""
        try:
            return datetime.fromisoformat(stamp)
        except ValueError:
            return datetime.min

    notes.sort(key=sort_key, reverse=True)
    return notes

def print_notes_list(notes):
    """Print the notes list in the standard C5 vertical-slice format.

    Output format: <id>  <created-date>  <title>  [tag1, tag2]
    Why a dedicated function: keeps the same output whether the user
    runs `notes0.py list` or types `list` in the interactive menu,
    which is the definition of a vertical slice — one feature end-to-end.
    """
    if not notes:
        # Empty-state hint helps first-time users know what to do next.
        print("No notes yet. Try: notes0.py create")
        return

    # Header row makes the columns readable at a glance.
    print(f"{'ID':<42}  {'CREATED':<10}  {'TITLE':<30}  TAGS")
    print("-" * 100)
    for note in notes:
        # Show only the date part (first 10 chars) to keep lines short.
        created_date = (note.get("created") or "")[:10]
        # Render tags as [a, b] or empty string when there are none.
        tags_str = "[" + ", ".join(note.get("tags") or []) + "]" if note.get("tags") else ""
        print(f"{note['id']:<42}  {created_date:<10}  {note['title']:<30}  {tags_str}")


def read_note(note_id):
    """Read and return note body text for a given note id."""
    # ID maps directly to one note file.
    note_file = NOTES_DIR / f"{note_id}{NOTE_EXTENSION}"
    if not note_file.exists():
        raise FileNotFoundError(f"Note not found: {note_id}")

    note_text = note_file.read_text(encoding="utf-8")
    note = parse_note(note_text)
    return note.content

def delete_note(note_id):
    """Delete a note by id."""
    note_file = NOTES_DIR / f"{note_id}{NOTE_EXTENSION}"
    if not note_file.exists():
        raise FileNotFoundError(f"Note not found: {note_id}")
    note_file.unlink()
    print(f"Deleted note: {note_file}")

def search_notes(query):
    """Search note files for the query in full text."""
    if not query or not query.strip():
        print("No search query provided. Please provide a query to search notes.")
        return []

    matches = []
    q = query.lower().strip()
    # Case-insensitive search across the full file contents.
    for note_file in NOTES_DIR.glob(f"*{NOTE_EXTENSION}"):
        try:
            note_text = note_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if q and q in note_text.lower():
            matches.append(note_file.name[: -len(NOTE_EXTENSION)])
    if not matches:
        print("No match found for query: {}".format(query))
    return matches


def help_command():
    """Alias for showing help text."""
    show_help()

def update_note(note_id, new_title="", new_content=""):
    """Update note title/content by id."""
    note_file = NOTES_DIR / f"{note_id}{NOTE_EXTENSION}"
    if not note_file.exists():
        raise FileNotFoundError(f"Note not found: {note_id}")

    note = parse_note(note_file.read_text(encoding="utf-8"))

    if new_title:
        note.title = new_title.strip()
    if new_content:
        note.content = new_content.strip()

    note.modified = datetime.now().isoformat(timespec="seconds")
    note.validate()
    _atomic_write_text(note_file, serialize_note(note))
    print(f"Updated note: {note_file}")

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
    list    - List all notes (id, date, title, tags)
    help    - Display this help information

Notes directory: {}
Default editor: {}
Note extension: {}
Preview chars: {}
    """.format(NOTES_DIR, DEFAULT_EDITOR, NOTE_EXTENSION, PREVIEW_CHARS)
    print(help_text.strip())




def finish(exit_code=0):
    """Clean up and exit the application."""
    # Current behavior: centralize process exit in one function.
    # Instructor likely wants: one place to control exit behavior across commands.
    sys.exit(exit_code)


def menu():
    """Show the available commands."""
    print("\nWhat would you like to do?")
    print("  help    - Show help information")
    print("  init    - Create the notes folder")
    print("  create  - Write a new note")
    print("  list    - Show all your notes")
    print("  search  - Search notes by keyword")
    print("  quit    - Exit\n")


def interactive_mode(notes_dir):
    """Run a simple menu loop so you can type commands one at a time."""
    print("Future Proof Notes Manager")
    print("Type a command below, or 'quit' to exit.")
    menu()

    while True:
        try:
            # Prompt-driven command loop for beginner-friendly usage.
            command = input("notes> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not command:
            continue

        if command == "quit":
            print("Goodbye!")
            break
        elif command == "help":
            show_help()
        elif command == "init":
            init_notes(notes_dir)
        elif command == "create":
            title = input("Title: ").strip()
            content = input("Content: ").strip()
            try:
                create_note(notes_dir, title, content)
            except ValueError as err:
                print(f"Error: {err}")
        elif command == "list":
            # Delegate to print_notes_list so interactive and CLI modes look identical.
            print_notes_list(list_notes())
        elif command == "search":
            query = input("Search for: ").strip()
            matches = search_notes(query)
            if matches:
                print("Found:")
                for note_id in matches:
                    print(f"  {note_id}")
        else:
            print(f"Unknown command '{command}'. Type 'help' to see options.")


def main():
    """Main entry point for the notes CLI application."""
    # Setup enforces folder existence on every run.
    notes_dir = setup()

    # If a command was passed in the terminal, run it directly.
    # Otherwise, open the interactive menu.
    if len(sys.argv) < 2:
        interactive_mode(notes_dir)
        finish(0)

    # Command-line mode supports single-command execution.
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
    elif command == "list":
        # C5: wire `notes0.py list` as a first-class CLI command.
        # Effect: `python notes0.py list` now works just like the interactive menu option.
        print_notes_list(list_notes())
        finish(0)
    else:
        print(f"Unknown command '{command}'. Try 'notes0.py help' for options.")
        finish(1)


if __name__ == "__main__":
    main()

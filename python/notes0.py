#!/usr/bin/env python3

import sys
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import yaml
from config import DEFAULT_EDITOR, NOTE_EXTENSION, NOTES_DIR, PREVIEW_CHARS


def ensure_notes_dir(notes_dir=NOTES_DIR):
    try:
        notes_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        notes_dir.chmod(0o700)
        return notes_dir
    except OSError as err:
        raise RuntimeError(
            f"Could not prepare notes directory at {notes_dir}. "
            "Please check directory permissions."
        ) from err


def setup():
    return ensure_notes_dir(NOTES_DIR)


def init_notes(notes_dir):
    ensure_notes_dir(notes_dir)
    print(f"Notes directory ready: {notes_dir}")


def _slugify(text):
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in text.strip())
    parts = [part for part in cleaned.split("-") if part]
    return "-".join(parts) or "untitled"


def _generate_note_id(notes_dir, timestamp, title=""):
    slug = _slugify(title)[:30] if title else "untitled"
    base_id = f"note_{timestamp.strftime('%Y%m%d_%H%M%S')}_{slug}"

    note_id = base_id
    suffix = 2
    while (notes_dir / f"{note_id}{NOTE_EXTENSION}").exists():
        note_id = f"{base_id}-{suffix}"
        suffix += 1
    return note_id


@dataclass
class Note:

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
        if not self.title or not self.title.strip():
            raise ValueError("title is required")
        if not self.author or not self.author.strip():
            raise ValueError("author is required")
        if not isinstance(self.priority, int) or not (1 <= self.priority <= 5):
            raise ValueError("priority must be between 1 and 5")
        return self

    def to_text(self):
        return serialize_note(self)


def parse_note(text):
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
        id=str(metadata.get("id") or "").strip(),
        title=str(metadata.get("title") or "").strip(),
        author=str(metadata.get("author") or "").strip(),
        created=str(metadata.get("created") or "").strip(),
        modified=str(metadata.get("modified") or "").strip(),
        tags=tags,
        status=str(metadata.get("status", "draft")).strip() or "draft",
        priority=priority,
        content=body,
        extra_metadata=extra_metadata,
    )
    return note.validate()


def serialize_note(note):
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


def create_note(notes_dir, title, content, tags=None):
    if not title.strip():
        raise ValueError("title cannot be empty")
    if not content.strip():
        raise ValueError("content cannot be empty")

    clean_tags = [t.strip() for t in (tags or []) if t.strip()]

    init_notes(notes_dir)

    timestamp = datetime.now()
    author = os.getenv("USER", "").strip() or "unknown"
    note = Note(
        id=_generate_note_id(notes_dir, timestamp, title),
        title=title.strip(),
        author=author,
        created=timestamp.isoformat(timespec="seconds"),
        modified=timestamp.isoformat(timespec="seconds"),
        tags=clean_tags,
        status="draft",
        priority=3,
        content=content.strip(),
    ).validate()

    note_path = notes_dir / f"{note.id}{NOTE_EXTENSION}"
    _atomic_write_text(note_path, note.to_text())

    tag_hint = f"  tags: {clean_tags}" if clean_tags else ""
    print(f'Created: "{note.title}" [{note.id}]{tag_hint}')
    return note.id


def _build_skeleton():
    now = datetime.now().isoformat(timespec="seconds")
    author = os.getenv("USER", "").strip() or "unknown"
    return (
        "---\n"
        "title: \n"
        f"author: {author}\n"
        f"created: {now}\n"
        f"modified: {now}\n"
        "tags: []\n"
        "status: draft\n"
        "priority: 3\n"
        "---\n"
        "\n"
        "Write your note content here.\n"
    )


def create_note_with_editor(notes_dir, editor=None):
    import subprocess

    chosen_editor = editor or DEFAULT_EDITOR or "nano"

    tmp_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=NOTE_EXTENSION,
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(_build_skeleton())
            tmp_file = Path(f.name)

        result = subprocess.call([chosen_editor, str(tmp_file)])
        if result != 0:
            print("Editor exited with an error. Aborting.", file=sys.stderr)
            return None

        edited_text = tmp_file.read_text(encoding="utf-8")

        try:
            note = parse_note(edited_text)
        except ValueError as err:
            print(f"Could not read note: {err}. Aborting.", file=sys.stderr)
            return None

        if not note.title.strip():
            print("Title is empty. Aborting without saving.", file=sys.stderr)
            return None

        note.validate()

        init_notes(notes_dir)
        note_path = notes_dir / f"{note.id}{NOTE_EXTENSION}"
        _atomic_write_text(note_path, note.to_text())

        tag_hint = f"  tags: {note.tags}" if note.tags else ""
        print(f'Created: "{note.title}" [{note.id}]{tag_hint}')
        return note.id

    finally:
        if tmp_file and tmp_file.exists():
            tmp_file.unlink(missing_ok=True)


def list_notes():
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
    if not notes:
        print("No notes yet. Try: notes0.py create")
        return

    print(f"{'ID':<42}  {'CREATED':<10}  {'TITLE':<30}  TAGS")
    print("-" * 100)
    for note in notes:
        created_date = (note.get("created") or "")[:10]
        tags_str = "[" + ", ".join(note.get("tags") or []) + "]" if note.get("tags") else ""
        print(f"{note['id']:<42}  {created_date:<10}  {note['title']:<30}  {tags_str}")


def resolve_note_id_prefix(notes_dir, prefix):
    candidate_prefix = (prefix or "").strip()
    if not candidate_prefix:
        raise ValueError("note ID prefix is required")

    matches = sorted(
        note_file.stem
        for note_file in notes_dir.glob(f"*{NOTE_EXTENSION}")
        if note_file.stem.startswith(candidate_prefix)
    )

    if not matches:
        raise FileNotFoundError(f"No note matches prefix: {candidate_prefix}")
    if len(matches) > 1:
        match_lines = "\n".join(f"  {m}" for m in matches)
        raise ValueError(
            f"Ambiguous note prefix '{candidate_prefix}'. "
            "Matches:\n"
            f"{match_lines}"
        )
    return matches[0]


def read_note(note_id):
    note_file = NOTES_DIR / f"{note_id}{NOTE_EXTENSION}"
    if not note_file.exists():
        raise FileNotFoundError(f"Note not found: {note_id}")

    note_text = note_file.read_text(encoding="utf-8")
    note = parse_note(note_text)
    return note.content

def delete_note(note_id):
    note_file = NOTES_DIR / f"{note_id}{NOTE_EXTENSION}"
    if not note_file.exists():
        raise FileNotFoundError(f"Note not found: {note_id}")
    note_file.unlink()
    print(f"Deleted note: {note_file}")

def search_notes(query, filter_tags=None):
    filter_tags_lower = [t.lower().strip() for t in (filter_tags or []) if t.strip()]
    has_tag_filter = bool(filter_tags_lower)
    q = query.lower().strip() if (query and query.strip()) else None

    if not q and not has_tag_filter:
        print("No search query provided. Please provide a query to search notes.")
        return []

    matches = []
    for note_file in NOTES_DIR.glob(f"*{NOTE_EXTENSION}"):
        try:
            note_text = note_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        if has_tag_filter:
            try:
                note = parse_note(note_text)
            except ValueError:
                continue
            note_tags_lower = [t.lower() for t in note.tags]
            if not all(tag in note_tags_lower for tag in filter_tags_lower):
                continue

        if q and q not in note_text.lower():
            continue

        matches.append(note_file.name[: -len(NOTE_EXTENSION)])

    if not matches:
        label = query if q else "(tag filter only)"
        print(f"No match found for: {label}")
    return matches


def stats_notes():
    from collections import Counter
    parsed = []
    for note_file in NOTES_DIR.glob(f"*{NOTE_EXTENSION}"):
        try:
            note = parse_note(note_file.read_text(encoding="utf-8"))
            parsed.append(note)
        except (OSError, UnicodeDecodeError, ValueError):
            continue

    if not parsed:
        return {"total": 0, "unique_tags": 0, "top_tags": [], "oldest": None, "newest": None}

    all_tags = [tag for note in parsed for tag in note.tags]
    tag_counts = Counter(all_tags)

    dated = sorted(parsed, key=lambda n: n.created or "")

    return {
        "total": len(parsed),
        "unique_tags": len(tag_counts),
        "top_tags": tag_counts.most_common(5),
        "oldest": dated[0].id if dated else None,
        "newest": dated[-1].id if dated else None,
    }


def print_stats(stats, as_json=False):
    if as_json:
        import json
        out = dict(stats)
        out["top_tags"] = [{"tag": t, "count": c} for t, c in stats["top_tags"]]
        print(json.dumps(out, indent=2))
        return

    print(f"Total notes : {stats['total']}")
    print(f"Unique tags : {stats['unique_tags']}")
    if stats["top_tags"]:
        top = ", ".join(f"{t}({c})" for t, c in stats["top_tags"])
        print(f"Top tags    : {top}")
    print(f"Oldest      : {stats['oldest'] or 'n/a'}")
    print(f"Newest      : {stats['newest'] or 'n/a'}")


def help_command():
    show_help()

def update_note(note_id, new_title="", new_content=""):
    note_file = NOTES_DIR / f"{note_id}{NOTE_EXTENSION}"
    if not note_file.exists():
        raise FileNotFoundError(f"Note not found: {note_id}")

    note = parse_note(note_file.read_text(encoding="utf-8"))

    if new_title:
        note.title = new_title.strip()
    if new_content:
        note.content = new_content.strip()

    now = datetime.now()
    candidate_modified = now.isoformat(timespec="seconds")
    if candidate_modified == (note.modified or ""):
        now = now + timedelta(seconds=1)
        candidate_modified = now.isoformat(timespec="seconds")
    note.modified = candidate_modified

    note.validate()
    _atomic_write_text(note_file, serialize_note(note))
    print(f"Updated note: {note_file}")


def update_note_with_editor(notes_dir, note_id_prefix, editor=None):
    import subprocess

    resolved_id = resolve_note_id_prefix(notes_dir, note_id_prefix)
    note_file = notes_dir / f"{resolved_id}{NOTE_EXTENSION}"
    original_text = note_file.read_text(encoding="utf-8")
    original_note = parse_note(original_text)
    chosen_editor = editor or DEFAULT_EDITOR or "nano"

    tmp_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=NOTE_EXTENSION,
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(original_text)
            tmp_file = Path(f.name)

        while True:
            result = subprocess.call([chosen_editor, str(tmp_file)])
            if result != 0:
                print("Editor exited with an error. Aborting.", file=sys.stderr)
                return None

            edited_text = tmp_file.read_text(encoding="utf-8")
            try:
                edited_note = parse_note(edited_text)
            except ValueError as err:
                print(f"Invalid note format: {err}", file=sys.stderr)
                print("Please fix and save again.", file=sys.stderr)
                continue

            edited_note.id = original_note.id
            edited_note.created = original_note.created

            now = datetime.now()
            candidate_modified = now.isoformat(timespec="seconds")
            if candidate_modified == (original_note.modified or ""):
                now = now + timedelta(seconds=1)
                candidate_modified = now.isoformat(timespec="seconds")
            edited_note.modified = candidate_modified

            edited_note.validate()

            _atomic_write_text(note_file, serialize_note(edited_note))
            print(f"Updated note: {note_file}")
            return edited_note.id
    finally:
        if tmp_file and tmp_file.exists():
            tmp_file.unlink(missing_ok=True)

def show_help():
    help_text = """
Future Proof Notes Manager v0.0

Usage: notes0.py [command] [options]

Commands:
    init                   Create the notes directory if missing
    create [title] [body]  Create a note  (--editor opens $EDITOR; --tags a,b)
    read   <id|prefix>     Print one note's body text
    update <id|prefix>     Update title or content  (--editor opens $EDITOR)
    delete <id>            Delete one note  (prompts [y/N]; --yes skips prompt)
    list                   List all notes, newest first
    search [query]         Search notes  (--tag x --tag y for tag intersection)
    stats                  Show collection summary  (--json for machine output)
    help                   Display this help information

Global flags:
    --help / -h            Show this help and exit
    --debug                Show full traceback on unexpected errors

Notes directory : {notes_dir}
Default editor  : {editor}
Note extension  : {ext}
Exit the application with the given status code.

    Why: calling sys.exit() directly throughout main() scatters process-exit
    behaviour across many branches. One function means we can add cleanup
    (flush logs, close connections) in the future without touching every
    command handler.
    Effect: exit_code 0 signals success to the shell; any non-zero value
    signals failure, which matters for shell scripts and CI pipelines that
    check the exit status of commands.
Print the interactive-mode command menu.

    Why: the interactive loop calls this once on startup so the user
    immediately sees what they can type — no guessing required.
    Effect: purely display; does not read input or change any state.
    Adding a new command to interactive_mode() should be accompanied
    by a matching line here so the menu stays accurate.
Run the REPL-style interactive command loop.

    Why: not every user wants to type `python notes0.py <command>` each
    time. The interactive loop lets them stay inside the app and type short
    command words one at a time — friendlier for beginners.
    Effect: blocks until the user types 'quit' or sends EOF (Ctrl-D) or
    Ctrl-C. All commands available in CLI mode are also available here,
    and they produce identical output (same functions are called).
Top-level entry point: route argv commands or fall into interactive mode.

    Why: a single entry point keeps the startup sequence in one place —
    setup the directory, read the command, dispatch to the right handler.
    Effect: when called with a command (e.g. `notes0.py list`) it runs that
    command and exits with 0 (success) or 1 (error). When called with no
    arguments it opens interactive_mode(), which runs until the user quits.
    """

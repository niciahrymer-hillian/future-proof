#!/usr/bin/env python3
# ══════════════════════════════════════════════════════════════════════
# [MODULE] notes0_annotated.py
# Learning reference copy of notes0.py — production file is notes0.py
# This file keeps ALL docstrings and inline comments, and adds anatomy
# labels so you can see exactly what kind of construct every line is.
#
# ANATOMY GUIDE
# ─────────────────────────────────────────────────────────────────────
# [MODULE]     the file itself; Python runs top-to-bottom on import/exec
# [IMPORT]     loads stdlib / third-party / local code into this scope
# [CONSTANT]   module-level name imported from config; never reassigned
# [CLASS]      blueprint for creating objects; groups data + behaviour
# [FIELD]      class-level variable; each instance gets its own copy
# [DECORATOR]  @something above a class/function — modifies its behaviour
# [METHOD]     function defined inside a class; receives 'self' as arg 1
# [FUNCTION]   standalone callable; not attached to any class
# [PARAMETER]  variable declared in the def line; caller fills it in
# [ARGUMENT]   value passed at the call site — becomes the parameter
# [VARIABLE]   local name that holds a value inside a function scope
# [RETURN]     value sent back to the caller via `return`
# [LAYER]      logical group of functions with the same responsibility
# ══════════════════════════════════════════════════════════════════════
"""
Future Proof Notes Manager - Version Zero (CLI)
A personal notes manager using text files with YAML headers.
Command-line interface version.
"""

# ── [LAYER 1] IMPORTS ─────────────────────────────────────────────────

# [IMPORT] stdlib — always available, no install needed
import sys       # sys.argv (CLI args), sys.exit (quit the process)
import os        # os.getenv (env vars), os.fsync (flush to disk)
import tempfile  # tempfile.NamedTemporaryFile (safe temp files)
from dataclasses import dataclass, field  # dataclass builds __init__ etc automatically
from datetime import datetime, timedelta  # datetime.now(), timedelta(seconds=1)
from pathlib import Path                  # Path("/some/dir") — OO filesystem paths

# [IMPORT] third-party — installed via pip (listed in requirements.txt)
import yaml  # PyYAML: parses/dumps YAML frontmatter in note files

# [IMPORT] local — our own config.py in the same directory
from config import DEFAULT_EDITOR, NOTE_EXTENSION, NOTES_DIR, PREVIEW_CHARS
# [ARGUMENT breakdown] each name imported here becomes a module-level
# constant in this file — same value as defined in config.py:
#   NOTES_DIR       — Path object: where .note files live on disk
#   NOTE_EXTENSION  — str: ".note"
#   DEFAULT_EDITOR  — str: value of $EDITOR env var, or "nano"
#   PREVIEW_CHARS   — int: 120 (max body chars shown in `list`)


# ── [LAYER 2] DIRECTORY SETUP ─────────────────────────────────────────


# [FUNCTION] ensure_notes_dir
# [PARAMETER] notes_dir: Path — directory to create/verify; defaults to NOTES_DIR
# [RETURN]    Path — the same notes_dir, now guaranteed to exist
def ensure_notes_dir(notes_dir=NOTES_DIR):
    """Create the notes directory if missing and enforce private permissions.

    Why: every command that reads or writes notes needs this folder to exist.
    Centralising the setup here means individual commands don't each have to
    check for the folder — they call this once and move on.
    Effect: all callers (setup, init_notes, _atomic_write_text) get a
    guaranteed, correctly-permissioned directory or a clear error message.
    """
    try:
        # parents=True creates any missing parent directories automatically.
        # exist_ok=True means no error if the folder is already there.
        notes_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        # chmod is called every run so that even if the folder already existed
        # with wrong permissions, we correct them silently.
        notes_dir.chmod(0o700)
        return notes_dir   # [RETURN] Path — ready, correctly permissioned directory
    except OSError as err:
        # Wrap the low-level OS error in a friendlier message so the user
        # sees a plain-English explanation rather than an errno code.
        raise RuntimeError(
            f"Could not prepare notes directory at {notes_dir}. "
            "Please check directory permissions."
        ) from err


# [FUNCTION] setup
# [PARAMETER] none
# [RETURN]    Path — the notes directory (created if needed)
def setup():
    """Bootstrap the application and return the notes directory path.

    Why: main() and interactive_mode() both need a ready notes directory
    before they do anything else. Calling setup() once at the top of main()
    keeps that concern out of every individual command handler.
    Effect: returns a Path object that the rest of the program uses to
    locate note files; raises RuntimeError if the directory cannot be created.
    """
    return ensure_notes_dir(NOTES_DIR)  # [ARGUMENT] NOTES_DIR: the module-level constant from config


# [FUNCTION] init_notes
# [PARAMETER] notes_dir: Path — the directory to initialise
# [RETURN]    None (prints confirmation, no return value)
def init_notes(notes_dir):
    """Create the notes directory and confirm it is ready.

    Why: the `init` command gives users an explicit way to set up the folder
    and see confirmation — useful when running the app for the first time or
    after moving the notes directory.
    Effect: calls ensure_notes_dir (idempotent — safe to run multiple times),
    then prints the path so the user knows where their notes will be stored.
    """
    ensure_notes_dir(notes_dir)
    print(f"Notes directory ready: {notes_dir}")


# ── [LAYER 3] ID GENERATION HELPERS ──────────────────────────────────


# [FUNCTION] _slugify  (leading _ = private helper, not part of public API)
# [PARAMETER] text: str — any string (typically a note title)
# [RETURN]    str — lowercase, hyphen-separated, filesystem-safe slug
def _slugify(text):
    """Convert a title string into a lowercase, filesystem-safe slug.

    Why: note filenames must be safe across all operating systems — no spaces,
    special characters, or unicode that could break a path. Slugifying the
    title keeps the filename human-readable while staying safe.
    Effect: used by _generate_note_id() to build the filename portion of
    a note's ID (e.g. "My First Note" → "my-first-note").
    """
    # [VARIABLE] cleaned: str — title with every non-alphanumeric char replaced by "-"
    # Replace anything that isn't a letter or digit with a dash.
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in text.strip())
    # [VARIABLE] parts: list[str] — non-empty slug segments after splitting on "-"
    # Split on dashes and filter out empty strings caused by consecutive
    # non-alphanumeric characters (e.g. "hello!!world" → ["hello", "world"]).
    parts = [part for part in cleaned.split("-") if part]
    # Fall back to "untitled" so we never produce an empty filename segment.
    return "-".join(parts) or "untitled"  # [RETURN] str — e.g. "my-first-note"


# [FUNCTION] _generate_note_id  (private helper)
# [PARAMETER] notes_dir: Path — checked for collisions (two notes same second)
# [PARAMETER] timestamp: datetime — when the note is being created
# [PARAMETER] title: str — used to build the slug portion of the ID
# [RETURN]    str — unique ID like "note_20240430_143022_my-first-note"
def _generate_note_id(notes_dir, timestamp, title=""):
    """Build a unique, sortable note ID from a timestamp and title slug.

    Why: notes need stable, unique filenames that also sort chronologically.
    Embedding the timestamp first (YYYYMMDD_HHMMSS) means a plain directory
    listing shows notes in creation order without needing a database.
    Effect: returned ID is used as both the filename stem and the `id` field
    in the YAML frontmatter, so they always match.
    """
    # [VARIABLE] slug: str — title converted to filesystem-safe characters, max 30 chars
    # Truncate the slug to 30 chars so filenames stay manageable in terminals.
    slug = _slugify(title)[:30] if title else "untitled"
    # [VARIABLE] base_id: str — the timestamp+slug portion before collision-checking
    base_id = f"note_{timestamp.strftime('%Y%m%d_%H%M%S')}_{slug}"

    # Guard against the rare case where two notes are created in the same
    # second with the same title. Append -2, -3, etc. until the ID is unique.
    # [VARIABLE] note_id: str — starts as base_id, gets suffix appended if needed
    note_id = base_id
    # [VARIABLE] suffix: int — counter for collision resolution (2, 3, ...)
    suffix = 2
    while (notes_dir / f"{note_id}{NOTE_EXTENSION}").exists():
        note_id = f"{base_id}-{suffix}"
        suffix += 1
    return note_id  # [RETURN] str — guaranteed unique ID


# ── [LAYER 4] DATA MODEL ──────────────────────────────────────────────


# [DECORATOR] @dataclass — automatically generates __init__, __repr__, __eq__
# from the field declarations below, saving ~30 lines of boilerplate.
@dataclass
# [CLASS] Note — the single in-memory representation of one note
class Note:
    """Single source of truth for what a note looks like in memory.

    Why: keeping all note fields in one dataclass means every part of the
    program — parser, serializer, validator, API — works with the same
    shape. If the spec changes (e.g. adding a new field), you change it
    here and the rest of the code follows.
    Effect: create_note, parse_note, serialize_note, and update_note all
    create or receive a Note instance, so they share the same field names
    and defaults automatically.
    """

    # [FIELD] id: str — filename stem and YAML 'id' key (e.g. "note_20240430_...")
    id: str
    # [FIELD] title: str — human-readable note title; required, cannot be blank
    title: str
    # [FIELD] author: str — OS username at creation time; required
    author: str
    # [FIELD] created: str — ISO 8601 timestamp string, set once at creation
    created: str
    # [FIELD] modified: str — ISO 8601 timestamp, updated on every save
    modified: str
    # [FIELD] tags: list[str] — optional labels; field() provides a fresh [] per instance
    # Why field(default_factory=list)? Mutable defaults (like []) are shared across
    # all instances if written as `tags: list = []` — a common Python gotcha.
    tags: list[str] = field(default_factory=list)
    # [FIELD] status: str — workflow state; "draft" by default
    status: str = "draft"
    # [FIELD] priority: int — 1 (highest) to 5 (lowest); 3 is neutral default
    priority: int = 3
    # [FIELD] content: str — the body text below the YAML frontmatter
    content: str = ""
    # [FIELD] extra_metadata: dict — preserves unknown YAML keys so they aren't lost
    extra_metadata: dict = field(default_factory=dict)

    # [METHOD] validate
    # [PARAMETER] self — the Note instance being validated (implicit first arg)
    # [RETURN]    self — returns the same instance so callers can chain: Note(...).validate()
    def validate(self):
        """Check that required fields are present and within allowed ranges.

        Why: validation lives on the model (not in each command) so the
        rules are enforced consistently whether a note comes from the CLI,
        the interactive menu, the API, or the editor flow.
        Effect: raises ValueError with a clear message on the first broken
        rule; returns self on success so callers can chain: Note(...).validate().
        """
        # title and author are the minimum required metadata per the spec.
        if not self.title or not self.title.strip():
            raise ValueError("title is required")
        if not self.author or not self.author.strip():
            raise ValueError("author is required")
        # Priority is a 1–5 scale; anything outside that range is a data error.
        if not isinstance(self.priority, int) or not (1 <= self.priority <= 5):
            raise ValueError("priority must be between 1 and 5")
        return self  # [RETURN] Note — self, enabling method chaining

    # [METHOD] to_text
    # [PARAMETER] self — the Note instance to serialise
    # [RETURN]    str — the full note as a string (YAML frontmatter + body)
    def to_text(self):
        """Render this note as a saveable string (YAML frontmatter + body).

        Why: a thin convenience wrapper so callers can write note.to_text()
        instead of importing and calling serialize_note directly.
        Effect: delegates to serialize_note(), which validates before writing,
        so calling to_text() on an invalid note will also raise ValueError.
        """
        return serialize_note(self)  # [ARGUMENT] self — passes the Note instance to the module-level function


# ── [LAYER 5] PARSING & SERIALISING ──────────────────────────────────


# [FUNCTION] parse_note
# [PARAMETER] text: str — raw file content (YAML frontmatter + body)
# [RETURN]    Note — a fully validated Note instance
def parse_note(text):
    """Parse a raw note string into a validated Note model.

    Why: every place that reads a note file (list, read, update, search)
    needs to turn the same raw text into a structured object. One parser
    means one place to fix bugs or add fields.
    Effect: returns a fully validated Note on success; raises ValueError
    with a line number on any format or data error so callers can show
    the user exactly where the problem is.
    """
    # [VARIABLE] lines: list[str] — every line of the file as a list element
    lines = text.splitlines()
    # A note must start with '---' — this is the YAML frontmatter delimiter.
    if not lines or lines[0].strip() != "---":
        raise ValueError("Invalid note format: missing YAML frontmatter at line 1")

    # Find the closing '---' that ends the YAML block.
    # [VARIABLE] yaml_end: int — line index of the closing '---'; -1 means not found
    yaml_end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            yaml_end = i
            break
    if yaml_end == -1:
        raise ValueError("Invalid note format: missing closing '---' for YAML frontmatter")

    # Everything between the two '---' markers is YAML; everything after is the body.
    # [VARIABLE] yaml_text: str — the raw YAML block as a multi-line string
    yaml_text = "\n".join(lines[1:yaml_end])
    # [VARIABLE] body: str — the note's written content (everything after closing ---)
    body = "\n".join(lines[yaml_end + 1:]).strip()

    try:
        # yaml.safe_load returns None on an empty block; default to {} so we
        # can call .get() safely without checking for None first.
        # [VARIABLE] metadata: dict — the parsed YAML as a Python dictionary
        metadata = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as err:
        # Extract the line number from the error if available, then re-raise
        # as a ValueError so callers only need to catch one exception type.
        mark = getattr(err, "problem_mark", None)
        line_no = (mark.line + 2) if mark is not None else 2
        problem = getattr(err, "problem", str(err))
        raise ValueError(f"Invalid YAML frontmatter at line {line_no}: {problem}") from err

    if not isinstance(metadata, dict):
        raise ValueError("Invalid YAML frontmatter at line 2: expected key/value mapping")

    # Parse priority separately so we can give a specific error if it isn't an integer.
    # [VARIABLE] priority_raw — whatever YAML parsed (could be int, str, None)
    priority_raw = metadata.get("priority", 3)
    try:
        # [VARIABLE] priority: int — validated integer in range 1–5
        priority = int(priority_raw)
    except (TypeError, ValueError) as err:
        raise ValueError("Invalid YAML frontmatter at line 2: priority must be an integer") from err

    # Tags can be stored as a YAML list OR as a comma-separated string — both are valid.
    # This flexibility lets users hand-edit notes without strict formatting requirements.
    # [VARIABLE] tags_raw — raw value from YAML (list, str, or unexpected type)
    tags_raw = metadata.get("tags", [])
    if isinstance(tags_raw, list):
        # [VARIABLE] tags: list[str] — clean, trimmed tag strings
        tags = [str(tag).strip() for tag in tags_raw if str(tag).strip()]
    elif isinstance(tags_raw, str):
        tags = [tag.strip() for tag in tags_raw.split(",") if tag.strip()]
    else:
        raise ValueError("Invalid YAML frontmatter at line 2: tags must be a list or string")

    # Preserve any extra YAML keys the user added (e.g. custom fields).
    # Effect: round-tripping a note through parse → serialize won't silently
    # drop user-defined metadata that isn't part of our schema.
    # [VARIABLE] known_fields: set — the fields our schema understands
    known_fields = {"id", "title", "author", "created", "modified", "tags", "status", "priority"}
    # [VARIABLE] extra_metadata: dict — any YAML keys not in known_fields
    extra_metadata = {k: v for k, v in metadata.items() if k not in known_fields}

    # [VARIABLE] note: Note — constructed instance, not yet validated
    note = Note(
        # Use `or ""` before str() so YAML null values (e.g. `title: `) become ""
        # rather than the string "None". Effect: validate()'s empty-field checks
        # correctly catch fields that were left blank in the editor skeleton.
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
    # Validate immediately so that bad files are caught at read time, not later
    # when the note is used — this stops invalid data from spreading through the app.
    return note.validate()  # [RETURN] Note — validated instance


# [FUNCTION] serialize_note
# [PARAMETER] note: Note — the in-memory note to write out
# [RETURN]    str — "---\n<YAML>\n---\n\n<body>\n"
def serialize_note(note):
    """Turn a Note model back into the raw string that gets written to disk.

    Why: the inverse of parse_note. Any time we write a note — create,
    update, editor flow — we need a consistent, correctly-formatted string.
    Centralising this means the on-disk format never drifts between commands.
    Effect: the returned string always has the form:
        ---
        <YAML fields>
        ---

        <body content>
    sort_keys=False preserves the field order we define here (id first,
    then title, author, etc.) so hand-edited files look predictable.
    """
    # Validate before writing — stops a corrupt Note object from ever reaching disk.
    note.validate()

    # Build the metadata dict in display order (most important fields first).
    # id is optional for brand-new notes that don't have one assigned yet.
    # [VARIABLE] metadata: dict — ordered dict of fields to write as YAML
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

    # Re-attach any extra fields the user added so they aren't lost on save.
    for key, value in note.extra_metadata.items():
        if key not in metadata:
            metadata[key] = value

    # allow_unicode=True keeps non-ASCII characters (accents, emoji) readable
    # in the file rather than escaping them as \uXXXX sequences.
    # [VARIABLE] yaml_text: str — the YAML block as a string (no trailing newline)
    yaml_text = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{yaml_text}\n---\n\n{note.content.strip()}\n"  # [RETURN] str


# ── [LAYER 6] SAFE FILE WRITING ───────────────────────────────────────


# [FUNCTION] _atomic_write_text  (private helper)
# [PARAMETER] target_path: Path — the final destination file
# [PARAMETER] text: str — content to write
# [RETURN]    None — side effect is a file on disk
def _atomic_write_text(target_path, text):
    """Write text to disk without any risk of producing a half-written file.

    Why: if the program crashes or the machine loses power mid-write, a
    direct open-and-write would leave a truncated or empty file on disk.
    Writing to a temp file first and then renaming is an atomic operation on
    most filesystems — the old file stays intact until the new one is ready.
    Effect: create and update operations are safe even under unexpected
    interruption; no note file is ever left in a partial state.
    """
    # Make sure the destination directory exists before we try to write into it.
    ensure_notes_dir(target_path.parent)
    # [VARIABLE] tmp_file: Path | None — set inside the try block; used for cleanup
    tmp_file = None
    try:
        # Write to a hidden temp file in the same directory as the target.
        # Same directory matters because os.replace must be on the same filesystem.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,          # We'll delete it ourselves in the finally block
            dir=target_path.parent,
            prefix=".tmp-note-",
            suffix=target_path.suffix,
        ) as handle:
            handle.write(text)
            # flush() pushes data from Python's buffer to the OS.
            handle.flush()
            # fsync() forces the OS to write its buffer to physical storage.
            # Together they guarantee the data is actually on disk before rename.
            os.fsync(handle.fileno())
            tmp_file = Path(handle.name)
        # Atomic rename: on POSIX systems this is guaranteed to be atomic.
        # On Windows it replaces the target in one step (no in-between state).
        os.replace(tmp_file, target_path)
    finally:
        # If anything went wrong before the rename, clean up the temp file
        # so we don't leave hidden garbage files in the notes directory.
        if tmp_file and tmp_file.exists():
            tmp_file.unlink(missing_ok=True)


# ── [LAYER 7] NOTE OPERATIONS (CRUD) ─────────────────────────────────


# [FUNCTION] create_note
# [PARAMETER] notes_dir: Path — directory where the new file will be saved
# [PARAMETER] title: str — human-readable note title (required, non-blank)
# [PARAMETER] content: str — body text (required, non-blank)
# [PARAMETER] tags: list[str] | None — optional labels; None treated as []
# [RETURN]    str — the new note's ID (also its filename stem)
def create_note(notes_dir, title, content, tags=None):
    """Create a note with YAML frontmatter and body content.

    C6: tags is now an optional list of strings (e.g. ["python", "ideas"]).
    Passing None or an empty list both result in no tags on the note.
    Effect: callers can supply tags from CLI flags, prompts, or the API.
    """
    # Input validation happens early so we fail fast.
    if not title.strip():
        raise ValueError("title cannot be empty")
    if not content.strip():
        raise ValueError("content cannot be empty")

    # Normalize tags: treat None as an empty list, strip whitespace from each tag.
    # Effect: callers don't need to sanitize before passing in.
    # [VARIABLE] clean_tags: list[str] — trimmed, non-empty tag strings
    clean_tags = [t.strip() for t in (tags or []) if t.strip()]

    # Any command should be safe even when folders do not exist yet.
    init_notes(notes_dir)

    # [VARIABLE] timestamp: datetime — captured once so id and created match exactly
    timestamp = datetime.now()
    # Default author comes from OS user when available.
    # [VARIABLE] author: str — OS username, or "unknown" if not set
    author = os.getenv("USER", "").strip() or "unknown"
    # Build and validate one model object before writing anything to disk.
    # [VARIABLE] note: Note — the fully validated in-memory note
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
    ).validate()  # .validate() is called on the newly created Note instance (method chaining)

    # File name and frontmatter share the same ID.
    # [VARIABLE] note_path: Path — full path to the new .note file
    note_path = notes_dir / f"{note.id}{NOTE_EXTENSION}"
    _atomic_write_text(note_path, note.to_text())

    # C6: richer confirmation so the user immediately sees title + ID.
    # Effect: easier to verify what was created, especially in scripts.
    tag_hint = f"  tags: {clean_tags}" if clean_tags else ""
    print(f'Created: "{note.title}" [{note.id}]{tag_hint}')
    return note.id  # [RETURN] str — the new note's unique ID


# [FUNCTION] _build_skeleton  (private helper for editor flow)
# [PARAMETER] none
# [RETURN]    str — a pre-filled note template with all required YAML fields
def _build_skeleton():
    """Return a pre-filled note template string with all required YAML fields.

    C7: Why a skeleton? Opening a blank file forces the user to remember every
    field name and format. A skeleton shows the structure and lets them fill in
    the blanks — reducing errors and making the editor flow beginner-friendly.
    Effect: the skeleton is what gets written to the temp file before $EDITOR opens.
    """
    # [VARIABLE] now: str — current timestamp as ISO 8601 string
    now = datetime.now().isoformat(timespec="seconds")
    # [VARIABLE] author: str — pre-filled from OS username
    author = os.getenv("USER", "").strip() or "unknown"
    return (
        "---\n"
        "title: \n"           # Required — user must fill this in
        f"author: {author}\n"
        f"created: {now}\n"
        f"modified: {now}\n"
        "tags: []\n"           # Optional — user can add comma-separated values
        "status: draft\n"
        "priority: 3\n"
        "---\n"
        "\n"
        "Write your note content here.\n"
    )


# [FUNCTION] create_note_with_editor
# [PARAMETER] notes_dir: Path — where to save the finished note
# [PARAMETER] editor: str | None — override editor; None uses DEFAULT_EDITOR
# [RETURN]    str | None — the new note's ID on success, None on abort
def create_note_with_editor(notes_dir, editor=None):
    """Open $EDITOR with a pre-filled skeleton, validate the result, then save.

    C7: This is the editor-based create path. It:
      1. Writes a skeleton to a temp file so the user sees required fields.
      2. Opens the editor and waits for them to save and quit.
      3. Reads the file back and validates it (aborts if title is empty).
      4. Writes the note to the notes directory only if validation passes.
    Effect: no partial or empty files are ever saved — validation gates the write.

    Falls back to nano if editor is None and $EDITOR is not set.
    """
    import subprocess  # [IMPORT] subprocess (deferred) — launches external processes

    # [VARIABLE] chosen_editor: str — resolved editor command (e.g. "nano", "vim")
    # Determine which editor to use; nano is the last-resort fallback.
    chosen_editor = editor or DEFAULT_EDITOR or "nano"

    # Write skeleton to a temp file with a .note extension so editors
    # can apply syntax highlighting if configured.
    # [VARIABLE] tmp_file: Path | None — holds the temp file path for cleanup
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

        # Open the editor and block until the user closes it.
        # subprocess.call is used (not Popen) so we wait for it to finish.
        # [VARIABLE] result: int — editor exit code (0 = success, non-zero = error)
        result = subprocess.call([chosen_editor, str(tmp_file)])
        if result != 0:
            print("Editor exited with an error. Aborting.", file=sys.stderr)
            return None

        # Read back whatever the user saved.
        # [VARIABLE] edited_text: str — full file content after editing
        edited_text = tmp_file.read_text(encoding="utf-8")

        # Parse and validate before touching the notes directory.
        # If title is empty the user didn't fill in the skeleton — abort cleanly.
        try:
            # [VARIABLE] note: Note — parsed from the edited file
            note = parse_note(edited_text)
        except ValueError as err:
            print(f"Could not read note: {err}. Aborting.", file=sys.stderr)
            return None

        if not note.title.strip():
            # No file is written when title is missing — matches acceptance criteria.
            print("Title is empty. Aborting without saving.", file=sys.stderr)
            return None

        note.validate()

        # Safe to write now — validation passed.
        init_notes(notes_dir)
        # [VARIABLE] note_path: Path — destination file path
        note_path = notes_dir / f"{note.id}{NOTE_EXTENSION}"
        _atomic_write_text(note_path, note.to_text())

        tag_hint = f"  tags: {note.tags}" if note.tags else ""
        print(f'Created: "{note.title}" [{note.id}]{tag_hint}')
        return note.id  # [RETURN] str — new note ID

    finally:
        # Always clean up the temp file, even if something went wrong.
        if tmp_file and tmp_file.exists():
            tmp_file.unlink(missing_ok=True)


# ── [LAYER 8] LIST & DISPLAY ──────────────────────────────────────────


# [FUNCTION] list_notes
# [PARAMETER] none (reads from module-level NOTES_DIR)
# [RETURN]    list[dict] — metadata dicts, sorted newest-modified first
def list_notes():
    """Scan the notes directory and return metadata for every readable note.

    Why: the list command needs a structured view of all notes, not raw file
    contents. Returning a list of dicts (rather than Note objects) keeps the
    display layer decoupled from the model — print_notes_list only needs keys,
    not the full Note dataclass.
    Effect: bad/unreadable files are skipped with a warning (not a crash) so
    one corrupt note never prevents the whole list from showing.
    Returns notes sorted by `modified` descending so the most recently
    changed note always appears first.
    """
    # [VARIABLE] notes: list[dict] — accumulates one dict per readable note
    notes = []
    for note_file in NOTES_DIR.glob(f"*{NOTE_EXTENSION}"):
        try:
            note_text = note_file.read_text(encoding="utf-8")
            note = parse_note(note_text)
        except (OSError, UnicodeDecodeError, ValueError) as err:
            print(f"Skipping bad note '{note_file.name}': {err}")
            continue

        # [VARIABLE] preview: str — first PREVIEW_CHARS characters of the body
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

    # [FUNCTION inside FUNCTION] sort_key — defined locally, used only by notes.sort()
    # Nested functions like this are called "closures" — they can access variables
    # from the enclosing function (in this case the loop variable doesn't matter,
    # but the pattern is common for one-off sort helpers).
    def sort_key(item):
        # Prefer `modified` for sort order; fall back to `created` if modified
        # is missing; fall back to datetime.min so the item sorts to the bottom
        # rather than raising an exception.
        stamp = item.get("modified") or item.get("created") or ""
        try:
            return datetime.fromisoformat(stamp)
        except ValueError:
            return datetime.min

    # reverse=True means newest (largest timestamp) comes first.
    notes.sort(key=sort_key, reverse=True)
    return notes  # [RETURN] list[dict] — sorted metadata list


# [FUNCTION] print_notes_list
# [PARAMETER] notes: list[dict] — output of list_notes()
# [RETURN]    None — side effect: prints a formatted table to stdout
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
        # [VARIABLE] created_date: str — "YYYY-MM-DD" slice of the ISO timestamp
        created_date = (note.get("created") or "")[:10]
        # Render tags as [a, b] or empty string when there are none.
        # [VARIABLE] tags_str: str — formatted tag display or ""
        tags_str = "[" + ", ".join(note.get("tags") or []) + "]" if note.get("tags") else ""
        print(f"{note['id']:<42}  {created_date:<10}  {note['title']:<30}  {tags_str}")


# ── [LAYER 9] PREFIX RESOLUTION ───────────────────────────────────────


# [FUNCTION] resolve_note_id_prefix
# [PARAMETER] notes_dir: Path — directory to search
# [PARAMETER] prefix: str — the typed prefix (e.g. "note_2024")
# [RETURN]    str — the full note ID that matches the prefix
def resolve_note_id_prefix(notes_dir, prefix):
    """Resolve an ID prefix to one note ID, or raise helpful errors.

    Why: typing full note IDs is tedious because IDs include timestamps.
    Prefix resolution lets users type the first few characters while still
    keeping deterministic behavior.
    Effect:
      - One match: returns the full ID.
      - No matches: raises FileNotFoundError.
      - Multiple matches: raises ValueError listing matching IDs.
    """
    # [VARIABLE] candidate_prefix: str — stripped input; empty string triggers error
    candidate_prefix = (prefix or "").strip()
    if not candidate_prefix:
        raise ValueError("note ID prefix is required")

    # [VARIABLE] matches: list[str] — all IDs whose stem starts with candidate_prefix
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
    return matches[0]  # [RETURN] str — the single matching full ID


# ── [LAYER 10] READ / DELETE / SEARCH ────────────────────────────────


# [FUNCTION] read_note
# [PARAMETER] note_id: str — exact full ID (not a prefix)
# [RETURN]    str — the note's body text (no YAML frontmatter)
def read_note(note_id):
    """Load and return the body content of a single note by ID.

    Why: the `read` command (and API GET endpoint) need to show just the
    note's written content — not the raw YAML frontmatter the user doesn't
    care about at read time.
    Effect: raises FileNotFoundError with a clear message if the ID doesn't
    match any file, so callers can give the user a helpful error rather than
    a cryptic stack trace.
    """
    # The ID is the filename stem, so this maps directly to one file on disk.
    # [VARIABLE] note_file: Path — full path to the .note file
    note_file = NOTES_DIR / f"{note_id}{NOTE_EXTENSION}"
    if not note_file.exists():
        raise FileNotFoundError(f"Note not found: {note_id}")

    note_text = note_file.read_text(encoding="utf-8")
    note = parse_note(note_text)
    # Return just the body content — callers that need metadata should call
    # parse_note() directly.
    return note.content  # [RETURN] str — body text only


# [FUNCTION] delete_note
# [PARAMETER] note_id: str — exact full ID of the note to remove
# [RETURN]    None — side effect: file is deleted from disk
def delete_note(note_id):
    """Permanently remove a note file from the notes directory.

    Why: deletion is intentionally a simple, irreversible file removal.
    There is no recycle bin or soft delete — this matches the design goal
    of keeping the storage layer as simple as plain files.
    Effect: raises FileNotFoundError if the note doesn't exist so the caller
    can tell the user the ID was wrong rather than silently doing nothing.
    """
    # [VARIABLE] note_file: Path — the file to unlink
    note_file = NOTES_DIR / f"{note_id}{NOTE_EXTENSION}"
    if not note_file.exists():
        raise FileNotFoundError(f"Note not found: {note_id}")
    note_file.unlink()  # unlink() = delete the file (Path method)
    print(f"Deleted note: {note_file}")


# [FUNCTION] search_notes
# [PARAMETER] query: str — full-text search term (can be "" if filter_tags given)
# [PARAMETER] filter_tags: list[str] | None — require ALL tags (intersection)
# [RETURN]    list[str] — IDs of matching notes
def search_notes(query, filter_tags=None):
    """Return IDs of all notes matching the query string and/or tag filters.

    Why: simple full-text search lets users find notes without remembering
    the exact title or ID. Searching the entire file (YAML + body) means
    tags, author, and content are all matched — no separate index needed.
    filter_tags: when provided, only notes that contain ALL listed tags are
    returned (intersection). `--tag a --tag b` finds notes tagged with both.
    Effect: returns a list of note IDs. Files that can't be read are skipped
    silently — a bad file never stops a search.
    """
    # [VARIABLE] filter_tags_lower: list[str] — normalized tag filter values
    filter_tags_lower = [t.lower().strip() for t in (filter_tags or []) if t.strip()]
    # [VARIABLE] has_tag_filter: bool — True when at least one tag filter exists
    has_tag_filter = bool(filter_tags_lower)
    # Normalize query to None when blank so comparisons below are clean.
    # [VARIABLE] q: str | None — lowercase query, or None if blank
    q = query.lower().strip() if (query and query.strip()) else None

    if not q and not has_tag_filter:
        print("No search query provided. Please provide a query to search notes.")
        return []

    # [VARIABLE] matches: list[str] — IDs of notes that pass all filters
    matches = []
    for note_file in NOTES_DIR.glob(f"*{NOTE_EXTENSION}"):
        try:
            note_text = note_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # Skip unreadable files (e.g. permission errors, encoding problems)
            # rather than crashing the whole search.
            continue

        # Tag filter: parse the note to access its structured tag list.
        # Short-circuit: if tags don't match, skip the text check entirely.
        if has_tag_filter:
            try:
                note = parse_note(note_text)
            except ValueError:
                continue
            # [VARIABLE] note_tags_lower: list[str] — this note's tags lowercased
            note_tags_lower = [t.lower() for t in note.tags]
            # All requested tags must be present — intersection, not union.
            if not all(tag in note_tags_lower for tag in filter_tags_lower):
                continue

        # Text query check against full file text (YAML + body), case-insensitive.
        if q and q not in note_text.lower():
            continue

        matches.append(note_file.name[: -len(NOTE_EXTENSION)])

    if not matches:
        label = query if q else "(tag filter only)"
        print(f"No match found for: {label}")
    return matches  # [RETURN] list[str] — matching note IDs


# ── [LAYER 11] STATS ──────────────────────────────────────────────────


# [FUNCTION] stats_notes
# [PARAMETER] none (reads from module-level NOTES_DIR)
# [RETURN]    dict with keys: total, unique_tags, top_tags, oldest, newest
def stats_notes():
    """Scan all notes and return collection-level statistics.

    Why: users with large collections need a quick overview — total count,
    which tags exist, which notes are oldest and newest — without reading
    every note body individually. One pass through parsed metadata is enough.
    Effect: returns a dict with keys:
      total       — number of readable notes
      unique_tags — number of distinct tag values across all notes
      top_tags    — list of (tag, count) pairs, up to 5, most common first
      oldest      — note ID with the earliest `created` timestamp
      newest      — note ID with the latest `created` timestamp
    """
    from collections import Counter  # [IMPORT] deferred — only needed by this function
    # [VARIABLE] parsed: list[Note] — all successfully parsed Note objects
    parsed = []
    for note_file in NOTES_DIR.glob(f"*{NOTE_EXTENSION}"):
        try:
            note = parse_note(note_file.read_text(encoding="utf-8"))
            parsed.append(note)
        except (OSError, UnicodeDecodeError, ValueError):
            continue

    if not parsed:
        return {"total": 0, "unique_tags": 0, "top_tags": [], "oldest": None, "newest": None}

    # [VARIABLE] all_tags: list[str] — every tag from every note (with duplicates)
    all_tags = [tag for note in parsed for tag in note.tags]
    # [VARIABLE] tag_counts: Counter — maps tag → how many notes use it
    tag_counts = Counter(all_tags)

    # Sort by created timestamp; notes without one sort to the front ("" < any ISO date).
    # [VARIABLE] dated: list[Note] — same notes, sorted oldest-first by created field
    dated = sorted(parsed, key=lambda n: n.created or "")

    return {
        "total": len(parsed),
        "unique_tags": len(tag_counts),
        "top_tags": tag_counts.most_common(5),   # list of (tag, count) tuples
        "oldest": dated[0].id if dated else None,
        "newest": dated[-1].id if dated else None,
    }  # [RETURN] dict


# [FUNCTION] print_stats
# [PARAMETER] stats: dict — output of stats_notes()
# [PARAMETER] as_json: bool — True for machine-readable JSON output
# [RETURN]    None — prints to stdout
def print_stats(stats, as_json=False):
    """Display collection statistics in human-readable or JSON format.

    Why: separating data gathering (stats_notes) from display (print_stats)
    lets the API and tests get raw numbers without triggering printed output.
    Effect: with as_json=True the output is valid JSON, suitable for piping
    to other tools. Otherwise it's a compact, human-readable summary.
    """
    if as_json:
        import json  # [IMPORT] deferred — only needed for JSON output path
        # Convert top_tags from list-of-tuples to list-of-dicts for JSON serialisation.
        # [VARIABLE] out: dict — copy of stats with top_tags converted to JSON-friendly form
        out = dict(stats)
        out["top_tags"] = [{"tag": t, "count": c} for t, c in stats["top_tags"]]
        print(json.dumps(out, indent=2))
        return

    print(f"Total notes : {stats['total']}")
    print(f"Unique tags : {stats['unique_tags']}")
    if stats["top_tags"]:
        # [VARIABLE] top: str — comma-separated "tag(count)" summary
        top = ", ".join(f"{t}({c})" for t, c in stats["top_tags"])
        print(f"Top tags    : {top}")
    print(f"Oldest      : {stats['oldest'] or 'n/a'}")
    print(f"Newest      : {stats['newest'] or 'n/a'}")


# ── [LAYER 12] HELP & UPDATE ──────────────────────────────────────────


# [FUNCTION] help_command
# [PARAMETER] none
# [RETURN]    None — alias; delegates to show_help()
def help_command():
    """Thin alias so external callers can use help_command() instead of show_help().

    Why: the API and other wrappers may call help_command() by name; keeping
    the alias means renaming show_help() internally doesn't break those callers.
    Effect: delegates entirely to show_help() — no logic here.
    """
    show_help()


# [FUNCTION] update_note
# [PARAMETER] note_id: str — exact full ID of the note to update
# [PARAMETER] new_title: str — replacement title; "" means keep current
# [PARAMETER] new_content: str — replacement body; "" means keep current
# [RETURN]    None — side effect: file on disk is overwritten
def update_note(note_id, new_title="", new_content=""):
    """Overwrite a note's title and/or body content, updating its modified timestamp.

    Why: editing a note shouldn't require deleting and recreating it — that
    would change the ID and lose the original `created` timestamp. This function
    loads the existing note, applies only the fields that were provided, and
    writes it back, preserving everything else.
    Effect: only fields passed with non-empty strings are changed; omitting
    new_title leaves the title as-is, and omitting new_content leaves the body
    as-is. The `modified` field is always updated to reflect when the edit happened.
    Uses _atomic_write_text so the file is never left in a partial state.
    """
    # [VARIABLE] note_file: Path — path to the .note file to update
    note_file = NOTES_DIR / f"{note_id}{NOTE_EXTENSION}"
    if not note_file.exists():
        raise FileNotFoundError(f"Note not found: {note_id}")

    # Read and parse the existing note so we keep all current field values.
    note = parse_note(note_file.read_text(encoding="utf-8"))

    # Only overwrite the fields that were actually provided by the caller.
    if new_title:
        note.title = new_title.strip()
    if new_content:
        note.content = new_content.strip()

    # Always advance modified time so updates are visible in sort order.
    # If formatting to seconds would keep the same value, bump by +1s.
    # [VARIABLE] now: datetime — current time
    now = datetime.now()
    # [VARIABLE] candidate_modified: str — ISO 8601 formatted to seconds
    candidate_modified = now.isoformat(timespec="seconds")
    if candidate_modified == (note.modified or ""):
        now = now + timedelta(seconds=1)
        candidate_modified = now.isoformat(timespec="seconds")
    note.modified = candidate_modified

    note.validate()
    _atomic_write_text(note_file, serialize_note(note))
    print(f"Updated note: {note_file}")


# [FUNCTION] update_note_with_editor
# [PARAMETER] notes_dir: Path — directory containing the note
# [PARAMETER] note_id_prefix: str — full ID or unique prefix
# [PARAMETER] editor: str | None — override editor; None uses DEFAULT_EDITOR
# [RETURN]    str | None — updated note ID on success, None on abort
def update_note_with_editor(notes_dir, note_id_prefix, editor=None):
    """Open an existing note in $EDITOR, validate on save, and write back.

    Why: full-note editing is easier in a real editor than prompt-by-prompt.
    This flow also supports ID prefixes so users can quickly target a note.
    Effect:
      - Resolves prefix to one note ID (or reports ambiguity).
      - Preserves `created` and `id` from the original note.
      - Always updates `modified` to current time.
      - If YAML is invalid, prints the error and re-opens editor until valid.
    """
    import subprocess

    # [VARIABLE] resolved_id: str — the full ID resolved from the prefix
    resolved_id = resolve_note_id_prefix(notes_dir, note_id_prefix)
    note_file = notes_dir / f"{resolved_id}{NOTE_EXTENSION}"
    original_text = note_file.read_text(encoding="utf-8")
    # [VARIABLE] original_note: Note — parsed snapshot kept for id/created preservation
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

        while True:  # loop until valid YAML or user aborts
            result = subprocess.call([chosen_editor, str(tmp_file)])
            if result != 0:
                print("Editor exited with an error. Aborting.", file=sys.stderr)
                return None

            edited_text = tmp_file.read_text(encoding="utf-8")
            try:
                # [VARIABLE] edited_note: Note — freshly parsed from the edited file
                edited_note = parse_note(edited_text)
            except ValueError as err:
                # Re-prompt loop requirement: keep opening editor until YAML is valid.
                print(f"Invalid note format: {err}", file=sys.stderr)
                print("Please fix and save again.", file=sys.stderr)
                continue

            # Keep identity/history fields stable even if user edited them.
            edited_note.id = original_note.id
            edited_note.created = original_note.created

            # Guarantee modified advances even for same-second edits.
            now = datetime.now()
            candidate_modified = now.isoformat(timespec="seconds")
            if candidate_modified == (original_note.modified or ""):
                now = now + timedelta(seconds=1)
                candidate_modified = now.isoformat(timespec="seconds")
            edited_note.modified = candidate_modified

            edited_note.validate()

            _atomic_write_text(note_file, serialize_note(edited_note))
            print(f"Updated note: {note_file}")
            return edited_note.id  # [RETURN] str — updated note ID
    finally:
        if tmp_file and tmp_file.exists():
            tmp_file.unlink(missing_ok=True)


# ── [LAYER 13] HELP, FINISH, MENU ────────────────────────────────────


# [FUNCTION] show_help
# [PARAMETER] none
# [RETURN]    None — prints to stdout
def show_help():
    """Print available commands and current configuration to the terminal.

    Why: a user who doesn't know what commands exist should always be one
    step away from an answer — `notes0.py help` is that step.
    Showing the live config values (notes directory, editor, extension)
    helps diagnose setup issues without opening any config files.
    Effect: purely informational — prints and returns; no files are read
    or written.
    """
    # Embed the live config values so the output reflects the actual runtime
    # environment, not hardcoded placeholder text.
    # [VARIABLE] help_text: str — multi-line string with placeholders filled by .format()
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
    """.format(notes_dir=NOTES_DIR, editor=DEFAULT_EDITOR, ext=NOTE_EXTENSION)
    print(help_text.strip())


# [FUNCTION] finish
# [PARAMETER] exit_code: int — 0 = success, non-zero = failure
# [RETURN]    never returns — calls sys.exit()
def finish(exit_code=0):
    """Exit the application with the given status code.

    Why: calling sys.exit() directly throughout main() scatters process-exit
    behaviour across many branches. One function means we can add cleanup
    (flush logs, close connections) in the future without touching every
    command handler.
    Effect: exit_code 0 signals success to the shell; any non-zero value
    signals failure, which matters for shell scripts and CI pipelines that
    check the exit status of commands.
    """
    sys.exit(exit_code)


# [FUNCTION] menu
# [PARAMETER] none
# [RETURN]    None — prints to stdout
def menu():
    """Print the interactive-mode command menu.

    Why: the interactive loop calls this once on startup so the user
    immediately sees what they can type — no guessing required.
    Effect: purely display; does not read input or change any state.
    Adding a new command to interactive_mode() should be accompanied
    by a matching line here so the menu stays accurate.
    """
    print("\nWhat would you like to do?")
    print("  help    - Show help information")
    print("  init    - Create the notes folder")
    print("  create  - Write a new note")
    print("  read    - View one note by ID")
    print("  update  - Edit one note by ID")
    print("  delete  - Remove one note by ID")
    print("  list    - Show all your notes")
    print("  search  - Search notes by keyword")
    print("  stats   - Show collection summary")
    print("  quit    - Exit\n")


# ── [LAYER 14] INTERACTIVE MODE ───────────────────────────────────────


# [FUNCTION] interactive_mode
# [PARAMETER] notes_dir: Path — passed from main() after setup()
# [RETURN]    None — blocks until user quits; all output is via print()
def interactive_mode(notes_dir):
    """Run the REPL-style interactive command loop.

    Why: not every user wants to type `python notes0.py <command>` each
    time. The interactive loop lets them stay inside the app and type short
    command words one at a time — friendlier for beginners.
    Effect: blocks until the user types 'quit' or sends EOF (Ctrl-D) or
    Ctrl-C. All commands available in CLI mode are also available here,
    and they produce identical output (same functions are called).
    """
    print("Future Proof Notes Manager")
    print("Type a command below, or 'quit' to exit.")
    menu()

    while True:
        try:
            # Prompt-driven command loop for beginner-friendly usage.
            # [VARIABLE] command: str — lowercased input from the user
            command = input("notes> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            # EOFError  = Ctrl-D (end of input stream)
            # KeyboardInterrupt = Ctrl-C (user interrupted the process)
            # Wrap print() so a second Ctrl+C during the newline write
            # doesn't propagate another KeyboardInterrupt upward.
            try:
                print()
            except (EOFError, KeyboardInterrupt):
                pass
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
            # C6: prompt for optional tags in interactive mode.
            # Effect: interactive and CLI create are now feature-equivalent.
            tags_raw = input("Tags (comma-separated, optional): ").strip()
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
            try:
                create_note(notes_dir, title, content, tags=tags)
            except ValueError as err:
                print(f"Error: {err}")
        elif command == "read":
            note_id_prefix = input("Note ID or prefix: ").strip()
            if not note_id_prefix:
                print("Error: note ID or prefix is required")
                continue
            try:
                resolved_id = resolve_note_id_prefix(notes_dir, note_id_prefix)
                print(read_note(resolved_id))
            except (FileNotFoundError, ValueError) as err:
                print(f"Error: {err}")
        elif command == "update":
            note_id_prefix = input("Note ID or prefix: ").strip()
            if not note_id_prefix:
                print("Error: note ID or prefix is required")
                continue

            use_editor = input("Use editor? (y/N): ").strip().lower() == "y"
            if use_editor:
                try:
                    update_note_with_editor(notes_dir, note_id_prefix)
                except (FileNotFoundError, ValueError) as err:
                    print(f"Error: {err}")
                continue

            # Both fields are optional individually, but at least one change
            # must be provided or update has nothing to do.
            new_title = input("New title (leave blank to keep current): ").strip()
            new_content = input("New content (leave blank to keep current): ").strip()
            if not new_title and not new_content:
                print("Error: provide a new title or new content")
                continue

            try:
                resolved_id = resolve_note_id_prefix(notes_dir, note_id_prefix)
                update_note(resolved_id, new_title, new_content)
            except (FileNotFoundError, ValueError) as err:
                print(f"Error: {err}")
        elif command == "delete":
            note_id = input("Note ID: ").strip()
            if not note_id:
                print("Error: note ID is required")
                continue
            # Safety prompt — default 'no' means pressing Enter alone aborts.
            confirm = input(f"Delete '{note_id}'? [y/N]: ").strip().lower()
            if confirm != "y":
                print("Aborted.")
                continue
            try:
                delete_note(note_id)
            except FileNotFoundError as err:
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
        elif command == "stats":
            # Show collection summary in interactive mode.
            print_stats(stats_notes())
        else:
            print(f"Unknown command '{command}'. Type 'help' to see options.")


# ── [LAYER 15] CLI ENTRY POINT ────────────────────────────────────────


# [FUNCTION] main
# [PARAMETER] none — reads sys.argv directly
# [RETURN]    never returns — always ends with finish() → sys.exit()
def main():
    """Top-level entry point: route argv commands or fall into interactive mode.

    Why: a single entry point keeps the startup sequence in one place —
    setup the directory, read the command, dispatch to the right handler.
    Effect: when called with a command (e.g. `notes0.py list`) it runs that
    command and exits with 0 (success) or 1 (error). When called with no
    arguments it opens interactive_mode(), which runs until the user quits.
    """
    # --debug shows the full traceback on unexpected errors instead of a
    # terse message. Strip it early so it doesn't appear as a command word.
    # [VARIABLE] debug: bool — True when --debug flag is in argv
    debug = "--debug" in sys.argv
    if debug:
        sys.argv = [arg for arg in sys.argv if arg != "--debug"]

    # --help / -h works at any position: notes0.py --help  or  notes0.py create --help
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        show_help()
        finish(0)

    # Ensure the notes directory exists before any command tries to use it.
    # [VARIABLE] notes_dir: Path — ready notes directory (from setup())
    notes_dir = setup()

    # No command argument → drop into the interactive prompt instead of
    # showing an error. This makes the app beginner-friendly: just run it.
    if len(sys.argv) < 2:
        interactive_mode(notes_dir)
        finish(0)

    # Command-line mode supports single-command execution.
    # [VARIABLE] command: str — the verb after the script name (e.g. "create", "list")
    command = sys.argv[1].lower()
    # sys.argv[0] = script name ("notes0.py")
    # sys.argv[1] = command     ("create")
    # sys.argv[2] = first arg   (e.g. "My Title")
    # sys.argv[3] = second arg  (e.g. "My content")

    if command == "help":
        show_help()
        finish(0)
    elif command == "init":
        init_notes(notes_dir)
        finish(0)
    elif command == "create":
        # C7: --editor flag opens $EDITOR with a pre-filled skeleton instead of prompting.
        # Usage: notes0.py create --editor
        # Effect: user can compose a full note in their preferred editor in one step.
        if "--editor" in sys.argv[2:]:
            result = create_note_with_editor(notes_dir)
            finish(0 if result else 1)

        # C6: Parse --tags flag from argv before collecting title/content.
        # Usage: notes0.py create "Title" "Body" --tags "python,ideas"
        # Effect: tags are optional; omitting --tags creates a note with no tags.
        tags = []
        args = sys.argv[2:]  # [VARIABLE] args: list[str] — everything after "create"
        if "--tags" in args:
            tag_index = args.index("--tags")
            # Expect the value to follow immediately: --tags "tag1,tag2"
            if tag_index + 1 < len(args):
                tags = [t.strip() for t in args[tag_index + 1].split(",") if t.strip()]
            # Remove --tags and its value so the remaining args are title + content.
            args = args[:tag_index] + args[tag_index + 2:]

        if len(args) >= 2:
            title = args[0]
            content = " ".join(args[1:])
        else:
            # Prompt fallback: ask for each field individually with clear labels.
            title = input("Title: ").strip()
            content = input("Content: ").strip()
            # C6: also ask for tags interactively when not given via flag.
            tags_raw = input("Tags (comma-separated, optional): ").strip()
            if tags_raw:
                tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        try:
            create_note(notes_dir, title, content, tags=tags)
            finish(0)
        except ValueError as err:
            print(f"Error: {err}", file=sys.stderr)
            finish(1)
    elif command == "read":
        # C8: read supports direct argument mode and prompt fallback.
        note_id_prefix = sys.argv[2].strip() if len(sys.argv) >= 3 else input("Note ID or prefix: ").strip()
        if not note_id_prefix:
            print("Error: note ID or prefix is required", file=sys.stderr)
            finish(1)
        try:
            resolved_id = resolve_note_id_prefix(notes_dir, note_id_prefix)
            print(read_note(resolved_id))
            finish(0)
        except (FileNotFoundError, ValueError) as err:
            print(f"Error: {err}", file=sys.stderr)
            finish(1)
    elif command == "update":
        # C11: update supports arg mode and prompt fallback.
        # Arg mode:    notes0.py update <id> "New title" "New content"
        # Prompt mode: notes0.py update
        note_id_prefix = sys.argv[2].strip() if len(sys.argv) >= 3 else input("Note ID or prefix: ").strip()
        if not note_id_prefix:
            print("Error: note ID or prefix is required", file=sys.stderr)
            finish(1)

        # Editor mode for C12-like workflow: notes0.py update <prefix> --editor
        if "--editor" in sys.argv[2:]:
            try:
                result = update_note_with_editor(notes_dir, note_id_prefix)
                finish(0 if result else 1)
            except (FileNotFoundError, ValueError) as err:
                print(f"Error: {err}", file=sys.stderr)
                finish(1)

        if len(sys.argv) >= 5:
            # Full argument mode: id + title + content
            new_title = sys.argv[3].strip()
            new_content = " ".join(sys.argv[4:]).strip()
        else:
            # Prompt fallback when fields are missing or command is interactive.
            new_title = input("New title (leave blank to keep current): ").strip()
            new_content = input("New content (leave blank to keep current): ").strip()

        if not new_title and not new_content:
            print("Error: provide a new title or new content", file=sys.stderr)
            finish(1)

        try:
            resolved_id = resolve_note_id_prefix(notes_dir, note_id_prefix)
            update_note(resolved_id, new_title, new_content)
            finish(0)
        except (FileNotFoundError, ValueError) as err:
            print(f"Error: {err}", file=sys.stderr)
            finish(1)
    elif command == "delete":
        # C9: delete supports direct argument mode and prompt fallback.
        note_id = sys.argv[2].strip() if len(sys.argv) >= 3 else input("Note ID: ").strip()
        if not note_id:
            print("Error: note ID is required", file=sys.stderr)
            finish(1)
        # Safety confirmation — default is 'no' so a plain Enter aborts.
        # --yes skips the prompt entirely for scripting and automation.
        if "--yes" not in sys.argv:
            confirm = input(f"Delete '{note_id}'? [y/N]: ").strip().lower()
            if confirm != "y":
                print("Aborted.")
                finish(0)
        try:
            delete_note(note_id)
            finish(0)
        except FileNotFoundError as err:
            print(f"Error: {err}", file=sys.stderr)
            finish(1)
    elif command == "list":
        # C5: wire `notes0.py list` as a first-class CLI command.
        # Effect: `python notes0.py list` now works just like the interactive menu option.
        print_notes_list(list_notes())
        finish(0)
    elif command == "stats":
        # Show collection summary: total notes, unique tags, top tags, oldest/newest.
        # --json outputs machine-readable JSON for piping to other tools.
        as_json = "--json" in sys.argv[2:]
        print_stats(stats_notes(), as_json=as_json)
        finish(0)
    elif command == "search":
        # C10: search supports text query, --tag filters, and prompt fallback.
        # Usage: notes0.py search "keyword"
        #        notes0.py search --tag python --tag ideas
        #        notes0.py search "keyword" --tag python
        # Multiple --tag flags return the intersection (notes with ALL tags).
        args = sys.argv[2:]
        filter_tags = []   # [VARIABLE] filter_tags: list[str] — collected --tag values
        remaining = []     # [VARIABLE] remaining: list[str] — non-flag args (the query)
        i = 0
        while i < len(args):
            if args[i] == "--tag" and i + 1 < len(args):
                filter_tags.append(args[i + 1])
                i += 2
            else:
                remaining.append(args[i])
                i += 1
        query = " ".join(remaining).strip()

        # Prompt only if neither query nor tag filter was provided on the command line.
        if not query and not filter_tags:
            query = input("Search for: ").strip()

        if not query and not filter_tags:
            print("Error: search query or --tag filter is required", file=sys.stderr)
            finish(1)

        matches = search_notes(query, filter_tags=filter_tags)
        if matches:
            print("Found:")
            for note_id in matches:
                print(f"  {note_id}")
            finish(0)

        # No-match is a successful search with zero results — exit 0.
        print("No matches.")
        finish(0)
    else:
        # Suggest near matches to help users who mistyped a command.
        # difflib.get_close_matches uses sequence similarity (not prefix matching).
        import difflib  # [IMPORT] deferred — stdlib, only needed for this branch
        known_commands = ["init", "create", "read", "update", "delete", "list", "search", "stats", "help"]
        # [VARIABLE] suggestions: list[str] — up to 1 close match from known_commands
        suggestions = difflib.get_close_matches(command, known_commands, n=1, cutoff=0.6)
        if suggestions:
            print(f"Unknown command '{command}'. Did you mean '{suggestions[0]}'? Try 'notes0.py help'.")
        else:
            print(f"Unknown command '{command}'. Try 'notes0.py help' for options.")
        finish(1)


# ── [ENTRY POINT GUARD] ───────────────────────────────────────────────
# __name__ == "__main__" is True only when this file is run directly:
#   python notes0.py list      → runs main()
# When imported by tests or another module:
#   import notes0              → skips this block; main() is NOT called
if __name__ == "__main__":
    main()

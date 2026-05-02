#!/usr/bin/env python3
"""
[ANATOMY] SQLite-based Note Repository Implementation — Annotated Reference Copy.

[ANATOMY: PURPOSE]
  This file is a reference copy of python/note_repository_sql.py with [ANATOMY]
  labels added to explain the structure and design decisions. It is NOT imported
  anywhere — it exists purely for learning and comparison.

WHY THIS FILE EXISTS:
  The NoteRepository interface allows swapping storage backends without changing the API.
  This implementation uses SQLite for persistent, queryable storage suitable for
  multi-user, server-based deployments (unlike file-based or in-memory storage).

HOW IT WORKS:
  - Each note is stored as a row in the 'notes' table
  - Uses user field to enforce ownership (same as UserScopedNoteRepository wraps)
  - Supports full-text search via SQL LIKE queries
  - Implements the same interface as FilesystemNoteRepository and MemoryNoteRepository

[ANATOMY: KEY CONCEPTS]
  1. Connection-per-operation: Each method opens and closes its own connection.
     WHY: SQLite supports only one writer at a time. Short-lived connections
     reduce locking risk in single-process deployments.

  2. row_factory = sqlite3.Row: Makes rows addressable by column name (row["id"])
     instead of index (row[0]). Makes the code readable without dataclasses.

  3. JSON columns: tags and extra_metadata are stored as JSON strings.
     WHY: SQLite has no native array or dict column types. JSON strings are
     compact and round-trip correctly via json.dumps / json.loads.

  4. Index on (user, modified DESC): Most queries are "notes for user X sorted
     by newest". This composite index lets SQLite skip a full table scan.

DATABASE SCHEMA:
  notes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    created TEXT NOT NULL,
    modified TEXT,
    content TEXT NOT NULL,
    tags TEXT,                  -- JSON array stored as string
    status TEXT DEFAULT 'draft',
    priority INTEGER DEFAULT 3,
    extra_metadata TEXT,        -- JSON stored as string
    user TEXT                   -- Username of note owner (for privacy)
  )
"""

# [ANATOMY: IMPORTS]
import json                     # Serialize/deserialize tags and extra_metadata
import sqlite3                  # Python built-in — no install required
from datetime import datetime, timedelta
from typing import List, Optional
from pathlib import Path

from note_repository import NoteRepository  # ABC this class implements
from notes0 import Note, _slugify           # Reuse Note dataclass and slug helper
from config import PREVIEW_CHARS            # How many chars to show in list preview


# [ANATOMY: CLASS — SQLiteNoteRepository]
class SQLiteNoteRepository(NoteRepository):
    """Persistent note storage using SQLite database.

    [ANATOMY: WHEN TO CHOOSE THIS BACKEND]
    - FilesystemNoteRepository: human-readable files, CLI-friendly, slow for queries
    - MemoryNoteRepository: zero I/O, ideal for unit tests, data lost on exit
    - SQLiteNoteRepository: persistent + queryable, best for server deployments

    LIMITATIONS:
      - SQLite handles ~100k notes efficiently; for millions, use PostgreSQL
      - SQLite doesn't support network access; use PostgreSQL for distributed systems
      - Each process holds a connection; high concurrency may cause "database locked" errors

    SCHEMA:
      - notes table: stores all note fields plus user (ownership)
      - indexed on (user, modified) for fast filtering/sorting
    """

    # [ANATOMY: __init__]
    def __init__(self, db_path: str = "/tmp/notes.db"):
        """Initialize SQLite repository.

        EFFECT: Creates database file and initializes schema if it doesn't exist.
        The default path /tmp/notes.db is suitable for quick local use.
        For production, pass an absolute path (e.g. "/var/data/notes.db").
        """
        self.db_path = db_path
        self._ensure_schema()   # Always safe to call — uses CREATE IF NOT EXISTS

    # [ANATOMY: CONNECTION HELPER]
    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with row factory enabled.

        WHY row_factory: By default sqlite3 returns tuples. Setting row_factory
        to sqlite3.Row makes rows accessible by column name (row["title"]) which
        is much more readable and less fragile than index-based access (row[1]).
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Access columns by name
        return conn

    # [ANATOMY: SCHEMA INITIALIZER]
    def _ensure_schema(self) -> None:
        """Create tables if they don't exist.

        WHY CREATE IF NOT EXISTS: Safe to call on every startup. If tables
        already exist, this is a no-op. Avoids needing migration logic for
        the simple case where the schema hasn't changed.

        WHY INDEX: The most common query pattern is "all notes for user X,
        newest first". The composite index (user, modified DESC) lets SQLite
        serve that query without scanning every row.
        """
        conn = self._get_connection()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    author TEXT NOT NULL,
                    created TEXT NOT NULL,
                    modified TEXT,
                    content TEXT NOT NULL,
                    tags TEXT,
                    status TEXT DEFAULT 'draft',
                    priority INTEGER DEFAULT 3,
                    extra_metadata TEXT,
                    user TEXT
                )
                """
            )
            # [ANATOMY: COMPOSITE INDEX]
            # Speeds up: SELECT * FROM notes WHERE user = ? ORDER BY modified DESC
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_user_modified 
                ON notes(user, modified DESC)
                """
            )
            conn.commit()
        finally:
            conn.close()

    # [ANATOMY: ROW DESERIALIZER]
    def _note_from_row(self, row: sqlite3.Row) -> Note:
        """Convert a database row to a Note object.

        WHY: The Note dataclass is the shared data contract across the entire app.
        Converting DB rows to Notes as early as possible means all calling code
        works with typed, validated Note objects rather than raw SQL rows.

        JSON COLUMNS: tags and extra_metadata are stored as JSON strings in the DB
        and parsed back to Python list/dict here. Empty/NULL values become [] / {}.
        """
        tags = json.loads(row["tags"]) if row["tags"] else []
        extra_metadata = json.loads(row["extra_metadata"]) if row["extra_metadata"] else {}

        return Note(
            id=row["id"],
            title=row["title"],
            author=row["author"],
            created=row["created"],
            modified=row["modified"],
            tags=tags,
            status=row["status"],
            priority=row["priority"],
            content=row["content"],
            extra_metadata=extra_metadata,
            user=row["user"] or "",   # Normalize NULL to empty string
        )

    # [ANATOMY: NOTE SERIALIZER]
    def _note_to_dict(self, note: Note) -> dict:
        """Convert a Note object to a dictionary for database insertion.

        WHY DICT: SQLite's execute() accepts named parameters via :key syntax
        when the parameter is a dict. This is safer than positional ? parameters
        because it's immune to column reordering.

        JSON SERIALIZATION: tags and extra_metadata must be converted to strings
        before storage since SQLite has no native array/dict column types.
        """
        return {
            "id": note.id,
            "title": note.title,
            "author": note.author,
            "created": note.created,
            "modified": note.modified,
            "tags": json.dumps(note.tags),              # list → JSON string
            "status": note.status,
            "priority": note.priority,
            "content": note.content,
            "extra_metadata": json.dumps(note.extra_metadata),  # dict → JSON string
            "user": note.user,
        }

    # [ANATOMY: add()]
    def add(self, title: str, content: str, tags: Optional[List[str]] = None, user: str = "") -> str:
        """Create a new note and store it in the database.

        FLOW:
          1. Validate title and content (raise ValueError if empty)
          2. Generate a collision-safe ID via _generate_id()
          3. Build a Note dataclass and call .validate()
          4. Insert the row using named parameter dict
          5. Return the generated ID

        WHY .validate() BEFORE INSERT: Notes in the DB should always be valid.
        Calling validate() here catches data errors before they reach the DB.
        """
        if not title.strip():
            raise ValueError("title cannot be empty")
        if not content.strip():
            raise ValueError("content cannot be empty")

        import os

        clean_tags = [t.strip() for t in (tags or []) if t.strip()]
        timestamp = datetime.now()
        author = os.getenv("USER", "").strip() or "unknown"

        note = Note(
            id=self._generate_id(timestamp, title),
            title=title.strip(),
            author=author,
            created=timestamp.isoformat(timespec="seconds"),
            modified=timestamp.isoformat(timespec="seconds"),
            tags=clean_tags,
            status="draft",
            priority=3,
            content=content.strip(),
            # [WHY] user is passed through and stored in the DB so ownership
            # checks in UserScopedNoteRepository work without extra queries.
            user=user,
        ).validate()

        conn = self._get_connection()
        try:
            note_dict = self._note_to_dict(note)
            # [ANATOMY: NAMED PARAMS] :id, :title, etc. match keys in note_dict.
            # This approach is safe against SQL injection — SQLite handles escaping.
            conn.execute(
                """
                INSERT INTO notes 
                (id, title, author, created, modified, tags, status, priority, content, extra_metadata, user)
                VALUES (:id, :title, :author, :created, :modified, :tags, :status, :priority, :content, :extra_metadata, :user)
                """,
                note_dict,
            )
            conn.commit()
        finally:
            conn.close()

        return note.id

    # [ANATOMY: get()]
    def get(self, note_id: str) -> Note:
        """Retrieve a note by ID. Raises FileNotFoundError if not found.

        WHY FileNotFoundError (not KeyError): Keeps consistent with
        FilesystemNoteRepository which raises FileNotFoundError when the
        .note file doesn't exist. All callers can use the same except clause.
        """
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
            if row is None:
                raise FileNotFoundError(f"Note not found: {note_id}")
            return self._note_from_row(row)
        finally:
            conn.close()

    # [ANATOMY: list_all()]
    def list_all(self) -> List[dict]:
        """Return summary dicts for all notes, newest-modified first.

        WHY DICTS NOT Notes: list_all() is used for displaying note lists in
        the UI/API. Returning full Note objects would expose the full content
        (potentially large) when only a preview is needed. Summaries are lighter.

        PREVIEW: Only the first PREVIEW_CHARS characters of content are included
        (newlines replaced with spaces for single-line display).
        """
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM notes ORDER BY modified DESC, created DESC"
            ).fetchall()

            result = []
            for row in rows:
                preview = row["content"].replace("\n", " ")[: PREVIEW_CHARS]
                result.append(
                    {
                        "id": row["id"],
                        "title": row["title"],
                        "created": row["created"],
                        "modified": row["modified"],
                        "tags": json.loads(row["tags"]) if row["tags"] else [],
                        "preview": preview,
                    }
                )
            return result
        finally:
            conn.close()

    # [ANATOMY: update()]
    def update(self, note_id: str, new_title: str = "", new_content: str = "") -> None:
        """Update a note's title and/or content.

        FLOW:
          1. Fetch existing row (raise FileNotFoundError if not found)
          2. Apply new_title / new_content if non-empty (partial update)
          3. Advance modified timestamp (add 1 second if same as current)
          4. Validate then write back

        WHY ADVANCE-BY-1: Timestamps are second-precision. If update() is called
        in the same second as creation, modified would equal created, making it
        impossible to tell whether the note was ever updated.
        """
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
            if row is None:
                raise FileNotFoundError(f"Note not found: {note_id}")

            note = self._note_from_row(row)

            if new_title:
                note.title = new_title.strip()
            if new_content:
                note.content = new_content.strip()

            # [ANATOMY: TIMESTAMP COLLISION GUARD]
            now = datetime.now()
            candidate_modified = now.isoformat(timespec="seconds")
            if candidate_modified == (note.modified or ""):
                now = now + timedelta(seconds=1)
                candidate_modified = now.isoformat(timespec="seconds")
            note.modified = candidate_modified

            note.validate()

            note_dict = self._note_to_dict(note)
            # [ANATOMY: PARTIAL UPDATE] Only title, content, modified are written.
            # Other fields (author, created, tags, status, priority, user) are
            # not touched by update() — intentional to preserve metadata integrity.
            conn.execute(
                """
                UPDATE notes SET 
                title = :title, 
                content = :content, 
                modified = :modified
                WHERE id = :id
                """,
                note_dict,
            )
            conn.commit()
        finally:
            conn.close()

    # [ANATOMY: delete()]
    def delete(self, note_id: str) -> None:
        """Delete a note by ID. Raises FileNotFoundError if not found.

        WHY CHECK rowcount: SQL DELETE succeeds even if no rows matched.
        Checking result.rowcount == 0 lets us raise FileNotFoundError
        (consistent with get/update) rather than silently succeeding.
        """
        conn = self._get_connection()
        try:
            result = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            if result.rowcount == 0:
                raise FileNotFoundError(f"Note not found: {note_id}")
            conn.commit()
        finally:
            conn.close()

    # [ANATOMY: search()]
    def search(self, query: str) -> List[str]:
        """Search notes by title or content. Returns list of note IDs.

        APPROACH: SQL LIKE with % wildcards — finds substrings in both title
        and content, case-insensitive via LOWER(). Returns IDs only (callers
        use get() to fetch full notes if needed).

        LIMITATION: LIKE is not full-text search — no ranking by relevance,
        no stemming, no stop-word removal. For more sophisticated search,
        consider SQLite FTS5 extension or a dedicated search library.
        """
        if not query or not query.strip():
            return []

        q = query.lower().strip()
        conn = self._get_connection()
        try:
            rows = conn.execute(
                """
                SELECT id FROM notes 
                WHERE LOWER(title) LIKE ? OR LOWER(content) LIKE ?
                ORDER BY modified DESC
                """,
                (f"%{q}%", f"%{q}%"),  # % wildcards = "anywhere in the string"
            ).fetchall()
            return [row["id"] for row in rows]
        finally:
            conn.close()

    # [ANATOMY: ID GENERATOR]
    def _generate_id(self, timestamp: datetime, title: str) -> str:
        """Generate a unique note ID (same format as notes0.py).

        FORMAT: note_YYYYMMDD_HHMMSS_slug-of-title
        COLLISION HANDLING: If an ID already exists in the DB (rare, same-second
        creation of same-titled notes), appends -2, -3, etc. until unique.

        WHY MATCH notes0.py FORMAT: All three backends produce identical-looking
        IDs, so note IDs are interchangeable regardless of which backend created them.
        """
        slug = _slugify(title)[:30] if title else "untitled"
        base_id = f"note_{timestamp.strftime('%Y%m%d_%H%M%S')}_{slug}"

        conn = self._get_connection()
        try:
            note_id = base_id
            suffix = 2
            while conn.execute("SELECT 1 FROM notes WHERE id = ?", (note_id,)).fetchone():
                note_id = f"{base_id}-{suffix}"
                suffix += 1
            return note_id
        finally:
            conn.close()

    # [ANATOMY: clear() — TESTING UTILITY]
    def clear(self) -> None:
        """Delete all notes from the database. Useful for testing.

        WHY NOT IN INTERFACE: clear() is not part of the NoteRepository ABC
        because clearing all notes is not a standard CRUD operation. It's only
        exposed on SQLiteNoteRepository for test setUp/tearDown use.
        """
        conn = self._get_connection()
        try:
            conn.execute("DELETE FROM notes")
            conn.commit()
        finally:
            conn.close()

#!/usr/bin/env python3
"""
SQLite-based Note Repository Implementation.

WHY THIS EXISTS:
  The NoteRepository interface allows swapping storage backends without changing the API.
  This implementation uses SQLite for persistent, queryable storage suitable for
  multi-user, server-based deployments (unlike file-based or in-memory storage).

HOW IT WORKS:
  - Each note is stored as a row in the 'notes' table
  - Uses user field to enforce ownership (same as UserScopedNoteRepository wraps)
  - Supports full-text search via SQL LIKE queries
  - Implements the same interface as FilesystemNoteRepository and MemoryNoteRepository

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

import json
import sqlite3
from datetime import datetime, timedelta
from typing import List, Optional
from pathlib import Path

from note_repository import NoteRepository
from notes0 import Note, _slugify
from config import PREVIEW_CHARS


class SQLiteNoteRepository(NoteRepository):
    """Persistent note storage using SQLite database.

    WHY: FilesystemNoteRepository reads/writes files on disk (slow for queries).
         MemoryNoteRepository loses data when the process exits (not persistent).
         SQLiteNoteRepository combines persistence (survives restarts) with
         query efficiency (SQL LIKE, WHERE clauses, indexing).

    WHEN TO USE:
      - Production deployments with multiple API servers
      - When you need complex queries or transactions
      - User-facing web app (not just CLI)

    LIMITATIONS:
      - SQLite handles ~100k notes efficiently; for millions, use PostgreSQL
      - SQLite doesn't support network access; use PostgreSQL for distributed systems
      - Each process holds a connection; high concurrency may cause "database locked" errors

    SCHEMA:
      - notes table: stores all note fields plus user (ownership)
      - indexed on (user, modified) for fast filtering/sorting
    """

    def __init__(self, db_path: str = "/tmp/notes.db"):
        """Initialize SQLite repository.

        EFFECT: Creates database file and initializes schema if it doesn't exist.
        """
        self.db_path = db_path
        self._ensure_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with row factory enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Access columns by name
        return conn

    def _ensure_schema(self) -> None:
        """Create tables if they don't exist."""
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
            # Index for fast filtering by user and sorting by modified
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_user_modified 
                ON notes(user, modified DESC)
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _note_from_row(self, row: sqlite3.Row) -> Note:
        """Convert a database row to a Note object."""
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
            user=row["user"] or "",
        )

    def _note_to_dict(self, note: Note) -> dict:
        """Convert a Note object to a dictionary for database insertion."""
        return {
            "id": note.id,
            "title": note.title,
            "author": note.author,
            "created": note.created,
            "modified": note.modified,
            "tags": json.dumps(note.tags),
            "status": note.status,
            "priority": note.priority,
            "content": note.content,
            "extra_metadata": json.dumps(note.extra_metadata),
            "user": note.user,
        }

    def add(self, title: str, content: str, tags: Optional[List[str]] = None, user: str = "") -> str:
        """Create a new note and store it in the database."""
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
            user=user,
        ).validate()

        conn = self._get_connection()
        try:
            note_dict = self._note_to_dict(note)
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

    def get(self, note_id: str) -> Note:
        """Retrieve a note by ID. Raises FileNotFoundError if not found."""
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
            if row is None:
                raise FileNotFoundError(f"Note not found: {note_id}")
            return self._note_from_row(row)
        finally:
            conn.close()

    def list_all(self) -> List[dict]:
        """Return summary dicts for all notes, newest-modified first."""
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

    def update(self, note_id: str, new_title: str = "", new_content: str = "") -> None:
        """Update a note's title and/or content."""
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

            # Update modified timestamp (advance by 1 second if identical to current)
            now = datetime.now()
            candidate_modified = now.isoformat(timespec="seconds")
            if candidate_modified == (note.modified or ""):
                now = now + timedelta(seconds=1)
                candidate_modified = now.isoformat(timespec="seconds")
            note.modified = candidate_modified

            note.validate()

            note_dict = self._note_to_dict(note)
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

    def delete(self, note_id: str) -> None:
        """Delete a note by ID. Raises FileNotFoundError if not found."""
        conn = self._get_connection()
        try:
            result = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            if result.rowcount == 0:
                raise FileNotFoundError(f"Note not found: {note_id}")
            conn.commit()
        finally:
            conn.close()

    def search(self, query: str) -> List[str]:
        """Search notes by title or content. Returns list of note IDs."""
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
                (f"%{q}%", f"%{q}%"),
            ).fetchall()
            return [row["id"] for row in rows]
        finally:
            conn.close()

    def _generate_id(self, timestamp: datetime, title: str) -> str:
        """Generate a unique note ID (same format as notes0.py)."""
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

    def clear(self) -> None:
        """Delete all notes from the database. Useful for testing."""
        conn = self._get_connection()
        try:
            conn.execute("DELETE FROM notes")
            conn.commit()
        finally:
            conn.close()

#!/usr/bin/env python3
"""
NoteRepository interface and implementations.

WHY THIS EXISTS:
  The API and tests should not need to know HOW notes are stored.
  This file defines the contract (NoteRepository) and two implementations:
    - FilesystemNoteRepository  → delegates to Phase 1 helpers in notes0.py
    - MemoryNoteRepository      → stores notes in a plain dict for fast, file-free tests

  Swapping storage backend (e.g. adding a database later) means writing a new
  class that satisfies the same interface — no endpoint code changes needed.
"""

import os
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import List, Optional

from config import NOTE_EXTENSION, PREVIEW_CHARS
from notes0 import (
    Note,
    _slugify,
    create_note,
    delete_note,
    ensure_notes_dir,
    list_notes,
    parse_note,
    search_notes,
    update_note,
)


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

class NoteRepository(ABC):
    """Abstract storage contract for notes.

    All CRUD operations go through this interface so the HTTP layer stays
    storage-agnostic.  Concrete implementations handle the details.
    """

    @abstractmethod
    def add(self, title: str, content: str, tags: Optional[List[str]] = None) -> str:
        """Create a new note and return its generated ID."""

    @abstractmethod
    def get(self, note_id: str) -> Note:
        """Return the full Note for the given ID.

        Raises FileNotFoundError if the note does not exist.
        """

    @abstractmethod
    def list_all(self) -> List[dict]:
        """Return summary dicts for all notes, newest-modified first."""

    @abstractmethod
    def update(self, note_id: str, new_title: str = "", new_content: str = "") -> None:
        """Overwrite title and/or content of an existing note.

        Raises FileNotFoundError if the note does not exist.
        """

    @abstractmethod
    def delete(self, note_id: str) -> None:
        """Remove a note permanently.

        Raises FileNotFoundError if the note does not exist.
        """

    @abstractmethod
    def search(self, query: str) -> List[str]:
        """Return IDs of notes whose text contains query (case-insensitive)."""


# ---------------------------------------------------------------------------
# Filesystem implementation
# ---------------------------------------------------------------------------

class FilesystemNoteRepository(NoteRepository):
    """Stores notes as YAML+Markdown files on disk.

    Delegates to the Phase 1 helpers in notes0.py so all existing file logic
    (atomic writes, ID generation, YAML parsing) is reused without duplication.

    NOTE: list_all, update, delete, and search delegate to notes0 helpers that
    read the global NOTES_DIR from config.  In production notes_dir is always
    the same path, so this is consistent.  Tests should use MemoryNoteRepository
    to avoid filesystem coupling entirely.
    """

    def __init__(self, notes_dir):
        self._notes_dir = notes_dir
        # Ensure the storage directory exists as soon as the repo is created.
        ensure_notes_dir(notes_dir)

    def add(self, title: str, content: str, tags: Optional[List[str]] = None) -> str:
        # create_note handles slugging, timestamping, collision avoidance, and atomic write.
        return create_note(self._notes_dir, title, content, tags)

    def get(self, note_id: str) -> Note:
        # Read and parse the raw file so callers get a full Note object, not just content.
        note_file = self._notes_dir / f"{note_id}{NOTE_EXTENSION}"
        if not note_file.exists():
            raise FileNotFoundError(f"Note not found: {note_id}")
        return parse_note(note_file.read_text(encoding="utf-8"))

    def list_all(self) -> List[dict]:
        return list_notes()

    def update(self, note_id: str, new_title: str = "", new_content: str = "") -> None:
        update_note(note_id, new_title=new_title, new_content=new_content)

    def delete(self, note_id: str) -> None:
        delete_note(note_id)

    def search(self, query: str) -> List[str]:
        return search_notes(query)


# ---------------------------------------------------------------------------
# In-memory implementation (for tests)
# ---------------------------------------------------------------------------

class MemoryNoteRepository(NoteRepository):
    """Stores notes in a plain dict — no files, no disk.

    WHY: Tests that use FilesystemNoteRepository write real files, which is
    slow and leaves cleanup work.  MemoryNoteRepository runs fast and resets
    automatically when the object is discarded.

    The behaviour mirrors FilesystemNoteRepository closely enough to catch
    real logic bugs: same ID format, same sort order, same validation rules.
    """

    def __init__(self):
        # Primary store: note_id -> Note object.
        self._store: dict[str, Note] = {}

    def _generate_id(self, timestamp: datetime, title: str) -> str:
        # Mirrors notes0._generate_note_id but checks the in-memory store
        # for collisions instead of the filesystem.
        slug = _slugify(title)[:30] if title else "untitled"
        base_id = f"note_{timestamp.strftime('%Y%m%d_%H%M%S')}_{slug}"
        note_id = base_id
        suffix = 2
        while note_id in self._store:
            note_id = f"{base_id}-{suffix}"
            suffix += 1
        return note_id

    def add(self, title: str, content: str, tags: Optional[List[str]] = None) -> str:
        if not title.strip():
            raise ValueError("title cannot be empty")
        if not content.strip():
            raise ValueError("content cannot be empty")

        timestamp = datetime.now()
        author = os.getenv("USER", "").strip() or "unknown"
        clean_tags = [t.strip() for t in (tags or []) if t.strip()]

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
        ).validate()

        self._store[note.id] = note
        return note.id

    def get(self, note_id: str) -> Note:
        if note_id not in self._store:
            raise FileNotFoundError(f"Note not found: {note_id}")
        return self._store[note_id]

    def list_all(self) -> List[dict]:
        def sort_key(note: Note):
            stamp = note.modified or note.created or ""
            try:
                return datetime.fromisoformat(stamp)
            except ValueError:
                return datetime.min

        result = []
        for note in sorted(self._store.values(), key=sort_key, reverse=True):
            preview = note.content.replace("\n", " ")[:PREVIEW_CHARS]
            result.append({
                "id": note.id,
                "title": note.title,
                "created": note.created,
                "modified": note.modified,
                "tags": note.tags,
                "preview": preview,
            })
        return result

    def update(self, note_id: str, new_title: str = "", new_content: str = "") -> None:
        if note_id not in self._store:
            raise FileNotFoundError(f"Note not found: {note_id}")

        note = self._store[note_id]
        if new_title:
            note.title = new_title.strip()
        if new_content:
            note.content = new_content.strip()

        # Advance modified timestamp; add a second if it would be identical to the current value.
        now = datetime.now()
        candidate = now.isoformat(timespec="seconds")
        if candidate == (note.modified or ""):
            candidate = (now + timedelta(seconds=1)).isoformat(timespec="seconds")
        note.modified = candidate

        note.validate()

    def delete(self, note_id: str) -> None:
        if note_id not in self._store:
            raise FileNotFoundError(f"Note not found: {note_id}")
        del self._store[note_id]

    def search(self, query: str) -> List[str]:
        if not query or not query.strip():
            return []
        q = query.lower().strip()
        # Match against both title and full content so results are consistent with
        # the filesystem implementation which searches the raw file text.
        return [
            note.id
            for note in self._store.values()
            if q in note.title.lower() or q in note.content.lower()
        ]


# ---------------------------------------------------------------------------
# User-scoped wrapper (enforces privacy)
# ---------------------------------------------------------------------------

class UserScopedNoteRepository(NoteRepository):
    """Wraps a NoteRepository to enforce per-user privacy.

    WHY THIS EXISTS:
      Without this, the underlying repositories return ALL notes globally.
      With this wrapper, every operation filters to only notes belonging to
      the authenticated user — users cannot see, modify, or delete other
      users' notes even if they somehow learn the note IDs.

    HOW IT WORKS:
      - Every method checks that the username matches the note's owner
      - Raises PermissionError if the user tries to access another user's note
      - set_user() is called by the API dependency to bind a username to
        each request's repository instance
    """

    def __init__(self, inner: NoteRepository):
        self._inner = inner
        self._username: Optional[str] = None

    def set_user(self, username: str) -> None:
        """Bind this repository to a specific user for the current request.

        EFFECT: All subsequent operations on this instance will enforce that
                the user can only access notes they own.
        """
        self._username = username

    def _check_owner(self, note: Note) -> None:
        """Raise PermissionError if the note is not owned by the current user."""
        if not self._username:
            raise PermissionError("No user context set for this repository")
        if note.user != self._username:
            raise PermissionError(f"Access denied: note belongs to {note.user}, not {self._username}")

    def add(self, title: str, content: str, tags: Optional[List[str]] = None) -> str:
        if not self._username:
            raise PermissionError("No user context set for this repository")
        # Create the note with inner repository; then retrieve and tag it with username.
        note_id = self._inner.add(title, content, tags)
        note = self._inner.get(note_id)
        note.user = self._username
        self._inner.update(note_id, new_title=note.title, new_content=note.content)
        return note_id

    def get(self, note_id: str) -> Optional[Note]:
        """Get a note if it exists and is owned by the current user. Returns None otherwise."""
        if not self._username:
            return None
        try:
            note = self._inner.get(note_id)
            if note.user != self._username:
                return None
            return note
        except FileNotFoundError:
            return None

    def list_all(self) -> List[dict]:
        """Return summary dicts for notes owned by the current user only."""
        if not self._username:
            return []
        
        # Get summary dicts from inner repo, then filter by checking the full Note object.
        all_summaries = self._inner.list_all()
        user_summaries = []
        
        for summary in all_summaries:
            note_id = summary.get("id")
            if not note_id:
                continue
            try:
                note = self._inner.get(note_id)
                if note.user == self._username:
                    user_summaries.append(summary)
            except FileNotFoundError:
                pass
        
        return user_summaries

    def update(self, note_id: str, new_title: str = "", new_content: str = "") -> None:
        """Update a note only if the current user owns it."""
        if not self._username:
            raise PermissionError("No user context set for this repository")
        
        try:
            note = self._inner.get(note_id)
            if note.user != self._username:
                raise PermissionError(f"Access denied: note belongs to {note.user}, not {self._username}")
            self._inner.update(note_id, new_title=new_title, new_content=new_content)
        except FileNotFoundError:
            raise

    def delete(self, note_id: str) -> None:
        """Delete a note only if the current user owns it."""
        if not self._username:
            raise PermissionError("No user context set for this repository")
        
        try:
            note = self._inner.get(note_id)
            if note.user != self._username:
                raise PermissionError(f"Access denied: note belongs to {note.user}, not {self._username}")
            self._inner.delete(note_id)
        except FileNotFoundError:
            raise

    def search(self, query: str) -> List[str]:
        """Search only the current user's notes."""
        if not self._username:
            return []
        
        # Search globally then filter to user's notes.
        all_matches = self._inner.search(query)
        user_matches = []
        for note_id in all_matches:
            try:
                note = self._inner.get(note_id)
                if note.user == self._username:
                    user_matches.append(note_id)
            except FileNotFoundError:
                pass
        return user_matches

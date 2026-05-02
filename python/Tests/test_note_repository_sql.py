#!/usr/bin/env python3
"""
Tests for SQLiteNoteRepository: verify SQL storage matches the NoteRepository interface.

Why: SQLiteNoteRepository should behave identically to FilesystemNoteRepository
and MemoryNoteRepository, just with persistent SQL storage instead of files/memory.
Effect: Tests validate that the SQL backend can replace other backends without
changing the API or behavior.
"""

import sys
import unittest
import tempfile
from pathlib import Path

PROJECT_PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_PYTHON_DIR))

from note_repository_sql import SQLiteNoteRepository


class TestSQLiteNoteRepositoryCRUD(unittest.TestCase):
    """Verify basic CRUD operations work in SQL storage."""

    def setUp(self):
        """Create a temporary database for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_notes.db")
        self.repo = SQLiteNoteRepository(db_path=self.db_path)

    def tearDown(self):
        """Clean up temporary database."""
        self.temp_dir.cleanup()

    def test_add_note_returns_id(self):
        """add() should create a note and return its ID."""
        note_id = self.repo.add("Test Note", "Test content")
        self.assertIsNotNone(note_id)
        self.assertIn("note_", note_id)

    def test_get_note_after_add(self):
        """get() should retrieve a note that was added."""
        note_id = self.repo.add("My Note", "My content")
        note = self.repo.get(note_id)
        
        self.assertEqual(note.title, "My Note")
        self.assertEqual(note.content, "My content")
        self.assertEqual(note.id, note_id)

    def test_get_nonexistent_note_raises_error(self):
        """get() should raise FileNotFoundError for missing notes."""
        with self.assertRaises(FileNotFoundError):
            self.repo.get("nonexistent-id")

    def test_add_note_with_tags(self):
        """add() should support tags."""
        note_id = self.repo.add("Tagged Note", "Content", tags=["python", "tutorial"])
        note = self.repo.get(note_id)
        
        self.assertEqual(note.tags, ["python", "tutorial"])

    def test_add_empty_title_raises_error(self):
        """add() should reject empty titles."""
        with self.assertRaises(ValueError):
            self.repo.add("", "Some content")

    def test_add_empty_content_raises_error(self):
        """add() should reject empty content."""
        with self.assertRaises(ValueError):
            self.repo.add("Title", "")

    def test_update_note_title(self):
        """update() should change a note's title."""
        note_id = self.repo.add("Original Title", "Content")
        self.repo.update(note_id, new_title="Updated Title")
        
        note = self.repo.get(note_id)
        self.assertEqual(note.title, "Updated Title")

    def test_update_note_content(self):
        """update() should change a note's content."""
        note_id = self.repo.add("Title", "Original content")
        self.repo.update(note_id, new_content="Updated content")
        
        note = self.repo.get(note_id)
        self.assertEqual(note.content, "Updated content")

    def test_update_modifies_timestamp(self):
        """update() should advance the modified timestamp."""
        note_id = self.repo.add("Title", "Content")
        original_note = self.repo.get(note_id)
        original_modified = original_note.modified
        
        # Wait a moment to ensure timestamp changes
        import time
        time.sleep(0.1)
        
        self.repo.update(note_id, new_title="Updated")
        updated_note = self.repo.get(note_id)
        
        # Modified should be different (newer)
        self.assertNotEqual(updated_note.modified, original_modified)

    def test_update_nonexistent_note_raises_error(self):
        """update() should raise FileNotFoundError for missing notes."""
        with self.assertRaises(FileNotFoundError):
            self.repo.update("nonexistent-id", new_title="New")

    def test_delete_note(self):
        """delete() should remove a note."""
        note_id = self.repo.add("To Delete", "Content")
        self.repo.delete(note_id)
        
        # Verify it's gone
        with self.assertRaises(FileNotFoundError):
            self.repo.get(note_id)

    def test_delete_nonexistent_note_raises_error(self):
        """delete() should raise FileNotFoundError for missing notes."""
        with self.assertRaises(FileNotFoundError):
            self.repo.delete("nonexistent-id")


class TestSQLiteNoteRepositoryListing(unittest.TestCase):
    """Verify listing and sorting works correctly."""

    def setUp(self):
        """Create a temporary database with sample data."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_notes.db")
        self.repo = SQLiteNoteRepository(db_path=self.db_path)

    def tearDown(self):
        """Clean up temporary database."""
        self.temp_dir.cleanup()

    def test_list_all_empty(self):
        """list_all() should return empty list when no notes exist."""
        notes = self.repo.list_all()
        self.assertEqual(notes, [])

    def test_list_all_returns_summaries(self):
        """list_all() should return summary dicts, not full Note objects."""
        note_id = self.repo.add("My Note", "My content here")
        notes = self.repo.list_all()
        
        self.assertEqual(len(notes), 1)
        summary = notes[0]
        
        # Should have these keys
        self.assertIn("id", summary)
        self.assertIn("title", summary)
        self.assertIn("created", summary)
        self.assertIn("modified", summary)
        self.assertIn("tags", summary)
        self.assertIn("preview", summary)

    def test_list_all_preview_truncation(self):
        """list_all() should truncate content preview to PREVIEW_CHARS."""
        long_content = "x" * 1000
        self.repo.add("Long Note", long_content)
        
        notes = self.repo.list_all()
        preview = notes[0]["preview"]
        
        # Preview should be shorter than full content
        self.assertLess(len(preview), len(long_content))

    def test_list_all_sorted_by_modified(self):
        """list_all() should sort by modified time, newest first."""
        import time
        
        note1_id = self.repo.add("Note 1", "Content 1")
        time.sleep(1.1)  # Sleep long enough to ensure different timestamps
        note2_id = self.repo.add("Note 2", "Content 2")
        time.sleep(1.1)
        note3_id = self.repo.add("Note 3", "Content 3")
        
        notes = self.repo.list_all()
        
        # Should be in reverse chronological order (newest first)
        # Note: timestamps are second-precision, so sleeping 1+ second ensures different seconds
        self.assertEqual(notes[0]["id"], note3_id)
        self.assertEqual(notes[1]["id"], note2_id)
        self.assertEqual(notes[2]["id"], note1_id)


class TestSQLiteNoteRepositorySearch(unittest.TestCase):
    """Verify search functionality works correctly."""

    def setUp(self):
        """Create a temporary database with searchable data."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_notes.db")
        self.repo = SQLiteNoteRepository(db_path=self.db_path)

    def tearDown(self):
        """Clean up temporary database."""
        self.temp_dir.cleanup()

    def test_search_empty_query(self):
        """search() with empty query should return empty list."""
        self.repo.add("Test", "Content")
        results = self.repo.search("")
        self.assertEqual(results, [])

    def test_search_by_title(self):
        """search() should find notes by title."""
        note_id = self.repo.add("Python Tutorial", "Learn Python")
        results = self.repo.search("Python")
        
        self.assertEqual(len(results), 1)
        self.assertIn(note_id, results)

    def test_search_by_content(self):
        """search() should find notes by content."""
        note_id = self.repo.add("My Note", "This is about Django")
        results = self.repo.search("Django")
        
        self.assertEqual(len(results), 1)
        self.assertIn(note_id, results)

    def test_search_case_insensitive(self):
        """search() should be case-insensitive."""
        note_id = self.repo.add("Python Guide", "Content")
        
        results_lower = self.repo.search("python")
        results_upper = self.repo.search("PYTHON")
        
        self.assertIn(note_id, results_lower)
        self.assertIn(note_id, results_upper)

    def test_search_multiple_matches(self):
        """search() should return multiple notes if all match."""
        id1 = self.repo.add("JavaScript Basics", "JS is awesome")
        id2 = self.repo.add("JavaScript Advanced", "Advanced JS topics")
        
        results = self.repo.search("JavaScript")
        
        self.assertEqual(len(results), 2)
        self.assertIn(id1, results)
        self.assertIn(id2, results)

    def test_search_no_matches(self):
        """search() should return empty list if no notes match."""
        self.repo.add("Python", "Content")
        results = self.repo.search("NonExistentKeyword")
        
        self.assertEqual(results, [])


class TestSQLiteNoteRepositoryPersistence(unittest.TestCase):
    """Verify data persists across repository instances."""

    def test_data_persists_across_instances(self):
        """Data added to one instance should be accessible from another."""
        temp_dir = tempfile.TemporaryDirectory()
        db_path = str(Path(temp_dir.name) / "persistent.db")
        
        try:
            # Create first instance and add data
            repo1 = SQLiteNoteRepository(db_path=db_path)
            note_id = repo1.add("Persistent Note", "This should persist")
            
            # Create second instance (new connection, same database)
            repo2 = SQLiteNoteRepository(db_path=db_path)
            note = repo2.get(note_id)
            
            # Should retrieve the note from the first instance
            self.assertEqual(note.title, "Persistent Note")
            self.assertEqual(note.content, "This should persist")
        finally:
            temp_dir.cleanup()

    def test_multiple_notes_persist(self):
        """Multiple notes should persist together."""
        temp_dir = tempfile.TemporaryDirectory()
        db_path = str(Path(temp_dir.name) / "multi.db")
        
        try:
            repo1 = SQLiteNoteRepository(db_path=db_path)
            id1 = repo1.add("Note 1", "Content 1")
            id2 = repo1.add("Note 2", "Content 2")
            id3 = repo1.add("Note 3", "Content 3")
            
            repo2 = SQLiteNoteRepository(db_path=db_path)
            notes = repo2.list_all()
            
            # Should have all 3 notes
            self.assertEqual(len(notes), 3)
            note_ids = {n["id"] for n in notes}
            self.assertIn(id1, note_ids)
            self.assertIn(id2, note_ids)
            self.assertIn(id3, note_ids)
        finally:
            temp_dir.cleanup()


class TestSQLiteNoteRepositoryUserField(unittest.TestCase):
    """Verify user field for ownership tracking."""

    def setUp(self):
        """Create a temporary database."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_notes.db")
        self.repo = SQLiteNoteRepository(db_path=self.db_path)

    def tearDown(self):
        """Clean up temporary database."""
        self.temp_dir.cleanup()

    def test_note_user_field_stored(self):
        """User field should be stored when creating a note."""
        # Note: add() doesn't currently set the user field; that's done by
        # UserScopedNoteRepository wrapper. But we can verify the field exists.
        note_id = self.repo.add("Test", "Content")
        note = self.repo.get(note_id)
        
        # User field should exist (but be empty since add() doesn't set it)
        self.assertEqual(note.user, "")


if __name__ == "__main__":
    unittest.main()

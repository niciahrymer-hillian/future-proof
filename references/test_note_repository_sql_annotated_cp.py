#!/usr/bin/env python3
"""
Tests for `SQLiteNoteRepository` — annotated reference copy.

[ANATOMY]
This file proves that the SQL backend behaves like the in-memory and filesystem
backends while adding persistence. It covers CRUD, listing, search, cross-instance
persistence, and the ownership field.
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
    """[CLASS] Basic create/read/update/delete expectations."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_notes.db")
        self.repo = SQLiteNoteRepository(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_add_note_returns_id(self):
        note_id = self.repo.add("Test Note", "Test content")
        self.assertIsNotNone(note_id)
        self.assertIn("note_", note_id)

    def test_get_note_after_add(self):
        note_id = self.repo.add("My Note", "My content")
        note = self.repo.get(note_id)
        self.assertEqual(note.title, "My Note")
        self.assertEqual(note.content, "My content")
        self.assertEqual(note.id, note_id)

    def test_get_nonexistent_note_raises_error(self):
        with self.assertRaises(FileNotFoundError):
            self.repo.get("nonexistent-id")

    def test_add_note_with_tags(self):
        note_id = self.repo.add("Tagged Note", "Content", tags=["python", "tutorial"])
        self.assertEqual(self.repo.get(note_id).tags, ["python", "tutorial"])

    def test_add_empty_title_raises_error(self):
        with self.assertRaises(ValueError):
            self.repo.add("", "Some content")

    def test_add_empty_content_raises_error(self):
        with self.assertRaises(ValueError):
            self.repo.add("Title", "")

    def test_update_note_title(self):
        note_id = self.repo.add("Original Title", "Content")
        self.repo.update(note_id, new_title="Updated Title")
        self.assertEqual(self.repo.get(note_id).title, "Updated Title")

    def test_update_note_content(self):
        note_id = self.repo.add("Title", "Original content")
        self.repo.update(note_id, new_content="Updated content")
        self.assertEqual(self.repo.get(note_id).content, "Updated content")

    def test_update_modifies_timestamp(self):
        import time
        note_id = self.repo.add("Title", "Content")
        original_modified = self.repo.get(note_id).modified
        time.sleep(0.1)
        self.repo.update(note_id, new_title="Updated")
        self.assertNotEqual(self.repo.get(note_id).modified, original_modified)

    def test_update_nonexistent_note_raises_error(self):
        with self.assertRaises(FileNotFoundError):
            self.repo.update("nonexistent-id", new_title="New")

    def test_delete_note(self):
        note_id = self.repo.add("To Delete", "Content")
        self.repo.delete(note_id)
        with self.assertRaises(FileNotFoundError):
            self.repo.get(note_id)

    def test_delete_nonexistent_note_raises_error(self):
        with self.assertRaises(FileNotFoundError):
            self.repo.delete("nonexistent-id")


class TestSQLiteNoteRepositoryListing(unittest.TestCase):
    """[CLASS] Summary listing and sort behavior."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_notes.db")
        self.repo = SQLiteNoteRepository(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_list_all_empty(self):
        self.assertEqual(self.repo.list_all(), [])

    def test_list_all_returns_summaries(self):
        self.repo.add("My Note", "My content here")
        summary = self.repo.list_all()[0]
        for key in ("id", "title", "created", "modified", "tags", "preview"):
            self.assertIn(key, summary)

    def test_list_all_preview_truncation(self):
        self.repo.add("Long Note", "x" * 1000)
        preview = self.repo.list_all()[0]["preview"]
        self.assertLess(len(preview), 1000)

    def test_list_all_sorted_by_modified(self):
        import time
        note1_id = self.repo.add("Note 1", "Content 1")
        time.sleep(1.1)
        note2_id = self.repo.add("Note 2", "Content 2")
        time.sleep(1.1)
        note3_id = self.repo.add("Note 3", "Content 3")
        notes = self.repo.list_all()
        self.assertEqual(notes[0]["id"], note3_id)
        self.assertEqual(notes[1]["id"], note2_id)
        self.assertEqual(notes[2]["id"], note1_id)


class TestSQLiteNoteRepositorySearch(unittest.TestCase):
    """[CLASS] Search semantics for title/content matching."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_notes.db")
        self.repo = SQLiteNoteRepository(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_search_empty_query(self):
        self.repo.add("Test", "Content")
        self.assertEqual(self.repo.search(""), [])

    def test_search_by_title(self):
        note_id = self.repo.add("Python Tutorial", "Learn Python")
        self.assertIn(note_id, self.repo.search("Python"))

    def test_search_by_content(self):
        note_id = self.repo.add("My Note", "This is about Django")
        self.assertIn(note_id, self.repo.search("Django"))

    def test_search_case_insensitive(self):
        note_id = self.repo.add("Python Guide", "Content")
        self.assertIn(note_id, self.repo.search("python"))
        self.assertIn(note_id, self.repo.search("PYTHON"))

    def test_search_multiple_matches(self):
        id1 = self.repo.add("JavaScript Basics", "JS is awesome")
        id2 = self.repo.add("JavaScript Advanced", "Advanced JS topics")
        results = self.repo.search("JavaScript")
        self.assertEqual(len(results), 2)
        self.assertIn(id1, results)
        self.assertIn(id2, results)

    def test_search_no_matches(self):
        self.repo.add("Python", "Content")
        self.assertEqual(self.repo.search("NonExistentKeyword"), [])


class TestSQLiteNoteRepositoryPersistence(unittest.TestCase):
    """[CLASS] Cross-instance persistence guarantees."""

    def test_data_persists_across_instances(self):
        temp_dir = tempfile.TemporaryDirectory()
        db_path = str(Path(temp_dir.name) / "persistent.db")
        try:
            repo1 = SQLiteNoteRepository(db_path=db_path)
            note_id = repo1.add("Persistent Note", "This should persist")
            repo2 = SQLiteNoteRepository(db_path=db_path)
            note = repo2.get(note_id)
            self.assertEqual(note.title, "Persistent Note")
            self.assertEqual(note.content, "This should persist")
        finally:
            temp_dir.cleanup()

    def test_multiple_notes_persist(self):
        temp_dir = tempfile.TemporaryDirectory()
        db_path = str(Path(temp_dir.name) / "multi.db")
        try:
            repo1 = SQLiteNoteRepository(db_path=db_path)
            id1 = repo1.add("Note 1", "Content 1")
            id2 = repo1.add("Note 2", "Content 2")
            id3 = repo1.add("Note 3", "Content 3")
            repo2 = SQLiteNoteRepository(db_path=db_path)
            notes = repo2.list_all()
            note_ids = {note["id"] for note in notes}
            self.assertEqual(len(notes), 3)
            self.assertIn(id1, note_ids)
            self.assertIn(id2, note_ids)
            self.assertIn(id3, note_ids)
        finally:
            temp_dir.cleanup()


class TestSQLiteNoteRepositoryUserField(unittest.TestCase):
    """[CLASS] Ownership metadata presence in SQL rows."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_notes.db")
        self.repo = SQLiteNoteRepository(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_note_user_field_stored(self):
        note_id = self.repo.add("Test", "Content")
        note = self.repo.get(note_id)
        self.assertEqual(note.user, "")


if __name__ == "__main__":
    unittest.main()

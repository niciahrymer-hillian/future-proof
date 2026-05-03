#!/usr/bin/env python3
"""
Repository interface consistency tests — annotated reference copy.

[ANATOMY]
This file answers one architectural question:
"Do MemoryNoteRepository and SQLiteNoteRepository behave the same way?"

[WHY THIS MATTERS]
The app swaps repositories through dependency injection. That only works safely
if every backend honors the same contract for add/get/list/update/search/delete
and validation behavior.
"""

import sys
import unittest
import tempfile
from pathlib import Path

PROJECT_PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_PYTHON_DIR))

from note_repository import MemoryNoteRepository
from note_repository_sql import SQLiteNoteRepository


def create_test_suite():
    """[HELPER] Run the same explicit operation sequence against both backends."""

    def run_interface_tests(repo, repo_name):
        """[VERIFY] Standard contract shared by all repository implementations."""
        note_id = repo.add("Test Note", "Test content", tags=["tag1"])
        note = repo.get(note_id)
        assert note.title == "Test Note", f"{repo_name}: title mismatch"
        assert note.content == "Test content", f"{repo_name}: content mismatch"
        assert "tag1" in note.tags, f"{repo_name}: tags mismatch"

        notes = repo.list_all()
        assert len(notes) == 1, f"{repo_name}: list_all count mismatch"
        assert notes[0]["id"] == note_id, f"{repo_name}: list_all ID mismatch"

        repo.update(note_id, new_title="Updated")
        updated_note = repo.get(note_id)
        assert updated_note.title == "Updated", f"{repo_name}: update failed"

        search_results = repo.search("Updated")
        assert note_id in search_results, f"{repo_name}: search failed"

        repo.delete(note_id)
        try:
            repo.get(note_id)
            assert False, f"{repo_name}: delete didn't work"
        except FileNotFoundError:
            pass

        try:
            repo.add("", "content")
            assert False, f"{repo_name}: empty title validation failed"
        except ValueError:
            pass

    memory_repo = MemoryNoteRepository()
    temp_dir = tempfile.TemporaryDirectory()
    sql_db = str(Path(temp_dir.name) / "test.db")
    sql_repo = SQLiteNoteRepository(db_path=sql_db)

    try:
        run_interface_tests(memory_repo, "MemoryNoteRepository")
        run_interface_tests(sql_repo, "SQLiteNoteRepository")
    finally:
        temp_dir.cleanup()


class QuickConsistencyTest(unittest.TestCase):
    """[CLASS] Single smoke test that enforces backend interchangeability."""

    def test_both_repositories_pass_identical_operations(self):
        create_test_suite()


if __name__ == "__main__":
    unittest.main()

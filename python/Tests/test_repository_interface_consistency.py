#!/usr/bin/env python3
"""
Interface Consistency Tests: Verify MemoryNoteRepository and SQLiteNoteRepository
behave identically for the same operations.

WHY THIS EXISTS:
  Two different storage backends should have identical behavior, so they're
  truly interchangeable. This test suite creates both types of repositories
  and runs the same operations against each, verifying identical results.

NOTE: We don't test FilesystemNoteRepository here because it uses the global
NOTES_DIR from config.py and delegates to notes0.py functions, making it
difficult to test in isolation. It's tested separately in test_note_repository.py.
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
    """Create an explicit test suite for both repository implementations.

    This avoids Python MRO (Method Resolution Order) complexity by explicitly
    running the same test logic against each backend in separate test functions.
    """

    def run_interface_tests(repo, repo_name):
        """Run a standard suite of interface tests against a repository."""
        print(f"\n  Testing {repo_name}...")

        # Test add/get
        note_id = repo.add("Test Note", "Test content", tags=["tag1"])
        note = repo.get(note_id)
        assert note.title == "Test Note", f"{repo_name}: title mismatch"
        assert note.content == "Test content", f"{repo_name}: content mismatch"
        assert "tag1" in note.tags, f"{repo_name}: tags mismatch"

        # Test list
        notes = repo.list_all()
        assert len(notes) == 1, f"{repo_name}: list_all count mismatch"
        assert notes[0]["id"] == note_id, f"{repo_name}: list_all ID mismatch"

        # Test update
        repo.update(note_id, new_title="Updated")
        updated_note = repo.get(note_id)
        assert updated_note.title == "Updated", f"{repo_name}: update failed"

        # Test search
        search_results = repo.search("Updated")
        assert note_id in search_results, f"{repo_name}: search failed"

        # Test delete
        repo.delete(note_id)
        try:
            repo.get(note_id)
            assert False, f"{repo_name}: delete didn't work"
        except FileNotFoundError:
            pass  # Expected

        # Test validation
        try:
            repo.add("", "content")
            assert False, f"{repo_name}: empty title validation failed"
        except ValueError:
            pass  # Expected

        print(f"    ✓ {repo_name} passed all interface tests")

    # Create repositories
    memory_repo = MemoryNoteRepository()
    temp_dir = tempfile.TemporaryDirectory()
    sql_db = str(Path(temp_dir.name) / "test.db")
    sql_repo = SQLiteNoteRepository(db_path=sql_db)

    try:
        # Run tests on both
        run_interface_tests(memory_repo, "MemoryNoteRepository")
        run_interface_tests(sql_repo, "SQLiteNoteRepository")
        print("\n  ✅ Both implementations pass identical interface tests\n")
    finally:
        temp_dir.cleanup()


class QuickConsistencyTest(unittest.TestCase):
    """Quick check that both repositories work the same way."""

    def test_both_repositories_pass_identical_operations(self):
        """Verify both Memory and SQL repositories pass the same operations."""
        create_test_suite()


if __name__ == "__main__":
    unittest.main()

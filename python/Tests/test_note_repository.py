#!/usr/bin/env python3
"""
Tests for UserScopedNoteRepository: verify note ownership privacy enforcement.

Why: Notes must be private. A user should only see/edit/delete their own notes.
Effect: This test suite ensures the privacy wrapper works correctly.
"""

import sys
import unittest
from datetime import datetime
from pathlib import Path

PROJECT_PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_PYTHON_DIR))

from auth import Role
from note_repository import MemoryNoteRepository, UserScopedNoteRepository


class TestUserScopedNoteRepositoryOwnershipEnforcement(unittest.TestCase):
    """Verify that users only see their own notes."""

    def setUp(self):
        """Create inner repo + user-scoped wrapper for each test."""
        self.inner_repo = MemoryNoteRepository()
        self.user_repo = UserScopedNoteRepository(self.inner_repo)

    def test_add_note_stores_current_user(self):
        """add() should attach the current user to the note."""
        self.user_repo.set_user("alice")
        note_id = self.user_repo.add("alice-note", "Alice's content")
        retrieved = self.user_repo.get(note_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.title, "alice-note")
        self.assertEqual(retrieved.user, "alice")

    def test_get_own_note_succeeds(self):
        """get() should return a note the user owns."""
        self.user_repo.set_user("alice")
        note_id = self.user_repo.add("Alice Note", "Content")
        
        # Still logged in as alice
        note = self.user_repo.get(note_id)
        self.assertIsNotNone(note)
        self.assertEqual(note.title, "Alice Note")

    def test_get_other_users_note_fails(self):
        """get() should return None for a note owned by another user."""
        # Create a note as bob
        self.user_repo.set_user("bob")
        bob_note_id = self.user_repo.add("Bob Note", "Bob's content")
        
        # Switch to alice and try to get bob's note
        self.user_repo.set_user("alice")
        note = self.user_repo.get(bob_note_id)
        self.assertIsNone(note)

    def test_list_all_only_shows_own_notes(self):
        """list_all() should only return notes owned by the current user."""
        # Create notes for alice
        self.user_repo.set_user("alice")
        alice_id1 = self.user_repo.add("Alice Note 1", "Content 1")
        alice_id2 = self.user_repo.add("Alice Note 2", "Content 2")
        
        # Create notes for bob
        self.user_repo.set_user("bob")
        bob_id1 = self.user_repo.add("Bob Note 1", "Bob content 1")
        bob_id2 = self.user_repo.add("Bob Note 2", "Bob content 2")
        
        # List as alice should only show alice's notes
        self.user_repo.set_user("alice")
        alice_notes = self.user_repo.list_all()
        alice_ids = {n["id"] for n in alice_notes}
        
        self.assertEqual(len(alice_ids), 2)
        self.assertIn(alice_id1, alice_ids)
        self.assertIn(alice_id2, alice_ids)
        self.assertNotIn(bob_id1, alice_ids)
        self.assertNotIn(bob_id2, alice_ids)

    def test_update_own_note_succeeds(self):
        """update() should succeed for a note the user owns."""
        self.user_repo.set_user("alice")
        note_id = self.user_repo.add("Original", "Original content")
        
        # Update as alice
        self.user_repo.update(note_id, "Updated Title", "Updated content")
        
        note = self.user_repo.get(note_id)
        self.assertEqual(note.title, "Updated Title")
        self.assertEqual(note.content, "Updated content")

    def test_update_other_users_note_fails(self):
        """update() should raise an exception for notes owned by another user."""
        # Create note as bob
        self.user_repo.set_user("bob")
        bob_note_id = self.user_repo.add("Bob's Note", "Bob's content")
        
        # Try to update as alice
        self.user_repo.set_user("alice")
        with self.assertRaises(PermissionError):
            self.user_repo.update(bob_note_id, "Hacked!", "Hacked content")

    def test_delete_own_note_succeeds(self):
        """delete() should succeed for a note the user owns."""
        self.user_repo.set_user("charlie")
        note_id = self.user_repo.add("To Delete", "Delete me")
        
        # Delete as charlie
        self.user_repo.delete(note_id)
        
        # Verify it's gone
        note = self.user_repo.get(note_id)
        self.assertIsNone(note)

    def test_delete_other_users_note_fails(self):
        """delete() should raise an exception for notes owned by another user."""
        # Create note as dave
        self.user_repo.set_user("dave")
        dave_note_id = self.user_repo.add("Dave's Note", "Dave's content")
        
        # Try to delete as eve
        self.user_repo.set_user("eve")
        with self.assertRaises(PermissionError):
            self.user_repo.delete(dave_note_id)
        
        # Verify it still exists in dave's context
        self.user_repo.set_user("dave")
        note = self.user_repo.get(dave_note_id)
        self.assertIsNotNone(note)

    def test_search_only_returns_own_notes(self):
        """search() should only return matches from the current user's notes."""
        # Alice creates some notes
        self.user_repo.set_user("alice")
        alice_python_id = self.user_repo.add("Python Tutorial", "Learn Python basics")
        self.user_repo.add("JavaScript Tutorial", "Learn JavaScript")
        
        # Bob creates notes with similar keywords
        self.user_repo.set_user("bob")
        bob_python_id = self.user_repo.add("Python Advanced", "Advanced Python topics")
        
        # Alice searches for "Python"
        self.user_repo.set_user("alice")
        results = self.user_repo.search("Python")
        
        # Should only find Alice's note, not Bob's
        self.assertEqual(len(results), 1)
        self.assertIn(alice_python_id, results)
        self.assertNotIn(bob_python_id, results)

    def test_set_user_none_blocks_access(self):
        """Without a current user, operations should fail or return empty."""
        # Add a note as alice
        self.user_repo.set_user("alice")
        note_id = self.user_repo.add("Alice's Note", "Content")
        
        # Clear the user
        self.user_repo.set_user(None)
        
        # Should not be able to access the note
        note = self.user_repo.get(note_id)
        self.assertIsNone(note)

    def test_different_users_have_separate_views(self):
        """Two different users should have completely separate note collections."""
        # Frank creates 3 notes
        self.user_repo.set_user("frank")
        frank_note1 = self.user_repo.add("Frank's Note 1", "Frank content 1")
        frank_note2 = self.user_repo.add("Frank's Note 2", "Frank content 2")
        frank_note3 = self.user_repo.add("Frank's Note 3", "Frank content 3")
        frank_list = self.user_repo.list_all()
        self.assertEqual(len(frank_list), 3)
        
        # Grace creates 2 notes
        self.user_repo.set_user("grace")
        grace_note1 = self.user_repo.add("Grace's Note 1", "Grace content 1")
        grace_note2 = self.user_repo.add("Grace's Note 2", "Grace content 2")
        grace_list = self.user_repo.list_all()
        self.assertEqual(len(grace_list), 2)
        
        # Frank's list should still only show 3
        self.user_repo.set_user("frank")
        frank_list_again = self.user_repo.list_all()
        self.assertEqual(len(frank_list_again), 3)


if __name__ == "__main__":
    unittest.main()

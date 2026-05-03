#!/usr/bin/env python3
"""
Tests for `UserScopedNoteRepository` — annotated reference copy.

[ANATOMY]
This file protects the privacy wrapper around note storage.
The inner repository may be memory, filesystem, or SQL, but once wrapped in
`UserScopedNoteRepository`, every operation must respect note ownership.

[WHY THIS FILE MATTERS]
The app's multi-user story depends on privacy guarantees. If this wrapper leaks,
users could read, edit, or delete each other's notes even if auth works.
"""

import sys
import unittest
from pathlib import Path

PROJECT_PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_PYTHON_DIR))

from note_repository import MemoryNoteRepository, UserScopedNoteRepository


class TestUserScopedNoteRepositoryOwnershipEnforcement(unittest.TestCase):
    """[CLASS] Ownership enforcement for add/get/list/update/delete/search."""

    def setUp(self):
        self.inner_repo = MemoryNoteRepository()
        self.user_repo = UserScopedNoteRepository(self.inner_repo)

    def test_add_note_stores_current_user(self):
        self.user_repo.set_user("alice")
        note_id = self.user_repo.add("alice-note", "Alice's content")
        retrieved = self.user_repo.get(note_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.title, "alice-note")
        self.assertEqual(retrieved.user, "alice")

    def test_get_own_note_succeeds(self):
        self.user_repo.set_user("alice")
        note_id = self.user_repo.add("Alice Note", "Content")
        note = self.user_repo.get(note_id)
        self.assertIsNotNone(note)
        self.assertEqual(note.title, "Alice Note")

    def test_get_other_users_note_fails(self):
        self.user_repo.set_user("bob")
        bob_note_id = self.user_repo.add("Bob Note", "Bob's content")
        self.user_repo.set_user("alice")
        self.assertIsNone(self.user_repo.get(bob_note_id))

    def test_list_all_only_shows_own_notes(self):
        self.user_repo.set_user("alice")
        alice_id1 = self.user_repo.add("Alice Note 1", "Content 1")
        alice_id2 = self.user_repo.add("Alice Note 2", "Content 2")
        self.user_repo.set_user("bob")
        bob_id1 = self.user_repo.add("Bob Note 1", "Bob content 1")
        bob_id2 = self.user_repo.add("Bob Note 2", "Bob content 2")
        self.user_repo.set_user("alice")
        alice_ids = {note["id"] for note in self.user_repo.list_all()}
        self.assertEqual(len(alice_ids), 2)
        self.assertIn(alice_id1, alice_ids)
        self.assertIn(alice_id2, alice_ids)
        self.assertNotIn(bob_id1, alice_ids)
        self.assertNotIn(bob_id2, alice_ids)

    def test_update_own_note_succeeds(self):
        self.user_repo.set_user("alice")
        note_id = self.user_repo.add("Original", "Original content")
        self.user_repo.update(note_id, "Updated Title", "Updated content")
        note = self.user_repo.get(note_id)
        self.assertEqual(note.title, "Updated Title")
        self.assertEqual(note.content, "Updated content")

    def test_update_other_users_note_fails(self):
        self.user_repo.set_user("bob")
        bob_note_id = self.user_repo.add("Bob's Note", "Bob's content")
        self.user_repo.set_user("alice")
        with self.assertRaises(PermissionError):
            self.user_repo.update(bob_note_id, "Hacked!", "Hacked content")

    def test_delete_own_note_succeeds(self):
        self.user_repo.set_user("charlie")
        note_id = self.user_repo.add("To Delete", "Delete me")
        self.user_repo.delete(note_id)
        self.assertIsNone(self.user_repo.get(note_id))

    def test_delete_other_users_note_fails(self):
        self.user_repo.set_user("dave")
        dave_note_id = self.user_repo.add("Dave's Note", "Dave's content")
        self.user_repo.set_user("eve")
        with self.assertRaises(PermissionError):
            self.user_repo.delete(dave_note_id)
        self.user_repo.set_user("dave")
        self.assertIsNotNone(self.user_repo.get(dave_note_id))

    def test_search_only_returns_own_notes(self):
        self.user_repo.set_user("alice")
        alice_python_id = self.user_repo.add("Python Tutorial", "Learn Python basics")
        self.user_repo.add("JavaScript Tutorial", "Learn JavaScript")
        self.user_repo.set_user("bob")
        bob_python_id = self.user_repo.add("Python Advanced", "Advanced Python topics")
        self.user_repo.set_user("alice")
        results = self.user_repo.search("Python")
        self.assertEqual(len(results), 1)
        self.assertIn(alice_python_id, results)
        self.assertNotIn(bob_python_id, results)

    def test_set_user_none_blocks_access(self):
        self.user_repo.set_user("alice")
        note_id = self.user_repo.add("Alice's Note", "Content")
        self.user_repo.set_user(None)
        self.assertIsNone(self.user_repo.get(note_id))

    def test_different_users_have_separate_views(self):
        self.user_repo.set_user("frank")
        self.user_repo.add("Frank's Note 1", "Frank content 1")
        self.user_repo.add("Frank's Note 2", "Frank content 2")
        self.user_repo.add("Frank's Note 3", "Frank content 3")
        self.assertEqual(len(self.user_repo.list_all()), 3)
        self.user_repo.set_user("grace")
        self.user_repo.add("Grace's Note 1", "Grace content 1")
        self.user_repo.add("Grace's Note 2", "Grace content 2")
        self.assertEqual(len(self.user_repo.list_all()), 2)
        self.user_repo.set_user("frank")
        self.assertEqual(len(self.user_repo.list_all()), 3)


if __name__ == "__main__":
    unittest.main()

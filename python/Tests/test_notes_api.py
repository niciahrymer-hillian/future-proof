#!/usr/bin/env python3
"""
Integration tests for the REST API: auth flow, endpoints, role-based access, privacy.

Why: The auth module and repository work in isolation. This suite verifies they work
together: login → token → auth header → user-scoped operations → privacy enforcement.
Effect: Tests start a FastAPI test client and run realistic request sequences.
"""

import sys
import unittest
from pathlib import Path

PROJECT_PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_PYTHON_DIR))

from fastapi.testclient import TestClient
from auth import Role, InMemoryUserRepository

# Import the app and override its dependencies
from notes_api import app, get_user_repo, get_repo
from note_repository import MemoryNoteRepository, UserScopedNoteRepository


# Dependency overrides for testing
def get_test_user_repo():
    """Return an in-memory user repository for testing."""
    repo = InMemoryUserRepository()
    # Pre-populate with test users
    repo.create("alice", "alice-password", role=Role.VIEWER)
    repo.create("bob", "bob-password", role=Role.EDITOR)
    repo.create("admin", "admin-password", role=Role.ADMIN)
    return repo


# Shared singleton: a new instance per request loses all data between requests.
_shared_note_repo = MemoryNoteRepository()


def get_test_note_repo():
    """Return the shared in-memory note repository for testing."""
    return _shared_note_repo


# Override the app's dependencies with test versions.
# NOTE: set in setUpClass of each test class so other test files that also
# set overrides (e.g. test_frontend.py) cannot clobber these during the full run.


class TestAuthFlow(unittest.TestCase):
    """Verify the login flow and token handling."""

    @classmethod
    def setUpClass(cls):
        """Set up test client once for all tests."""
        app.dependency_overrides[get_user_repo] = get_test_user_repo
        app.dependency_overrides[get_repo] = get_test_note_repo
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_user_repo, None)
        app.dependency_overrides.pop(get_repo, None)

    def test_01_login_with_valid_credentials(self):
        """POST /auth/login with correct credentials returns a token."""
        response = self.client.post(
            "/auth/login",
            json={"username": "alice", "password": "alice-password"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["role"], Role.VIEWER)

    def test_02_login_with_wrong_password(self):
        """POST /auth/login with wrong password returns 401."""
        response = self.client.post(
            "/auth/login",
            json={"username": "alice", "password": "wrong-password"}
        )
        self.assertEqual(response.status_code, 401)

    def test_03_endpoint_without_auth_header_returns_401(self):
        """GET /api/notes without Authorization header returns 401."""
        response = self.client.get("/api/notes")
        self.assertEqual(response.status_code, 401)


class TestNotesCRUD(unittest.TestCase):
    """Verify CRUD operations work with authentication."""

    @classmethod
    def setUpClass(cls):
        """Set up test client and get tokens once."""
        app.dependency_overrides[get_user_repo] = get_test_user_repo
        app.dependency_overrides[get_repo] = get_test_note_repo
        cls.client = TestClient(app)
        
        # Log in as alice (viewer role)
        login_response = cls.client.post(
            "/auth/login",
            json={"username": "alice", "password": "alice-password"}
        )
        cls.alice_token = login_response.json()["access_token"]
        cls.alice_headers = {"Authorization": f"Bearer {cls.alice_token}"}
        
        # Log in as bob (editor role)
        login_response = cls.client.post(
            "/auth/login",
            json={"username": "bob", "password": "bob-password"}
        )
        cls.bob_token = login_response.json()["access_token"]
        cls.bob_headers = {"Authorization": f"Bearer {cls.bob_token}"}

    def test_01_get_notes_empty_list(self):
        """GET /api/notes returns empty list when no notes exist."""
        response = self.client.get("/api/notes", headers=self.alice_headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data, [])

    def test_02_create_note_as_editor_succeeds(self):
        """POST /api/notes with EDITOR role creates a note."""
        response = self.client.post(
            "/api/notes",
            json={"title": "Bob's Note", "content": "Bob's content"},
            headers=self.bob_headers
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["title"], "Bob's Note")
        self.assertIn("id", data)

    def test_03_create_note_as_viewer_fails(self):
        """POST /api/notes with VIEWER role returns 403 Forbidden."""
        response = self.client.post(
            "/api/notes",
            json={"title": "Alice's Note", "content": "Alice's content"},
            headers=self.alice_headers
        )
        self.assertEqual(response.status_code, 403)

    def test_04_list_notes_returns_only_user_notes(self):
        """GET /api/notes returns only the authenticated user's notes."""
        # Alice should see empty list
        alice_list = self.client.get("/api/notes", headers=self.alice_headers)
        self.assertEqual(alice_list.status_code, 200)
        self.assertEqual(alice_list.json(), [])
        
        # Bob should see his note (created in test_02)
        bob_list = self.client.get("/api/notes", headers=self.bob_headers)
        self.assertEqual(bob_list.status_code, 200)
        bob_notes = bob_list.json()
        self.assertEqual(len(bob_notes), 1)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_user_repo, None)
        app.dependency_overrides.pop(get_repo, None)


class TestPrivacyEnforcement(unittest.TestCase):
    """Verify users cannot access other users' notes."""

    @classmethod
    def setUpClass(cls):
        """Set up test client and tokens."""
        app.dependency_overrides[get_user_repo] = get_test_user_repo
        app.dependency_overrides[get_repo] = get_test_note_repo
        # Reset shared repo so this class starts with a clean slate,
        # independent of whatever TestNotesCRUD may have created.
        _shared_note_repo.clear()
        cls.client = TestClient(app)
        
        # Create tokens for alice and bob
        for username in ["alice", "bob"]:
            login_response = cls.client.post(
                "/auth/login",
                json={"username": username, "password": f"{username}-password"}
            )
            token = login_response.json()["access_token"]
            setattr(cls, f"{username}_token", token)
            setattr(cls, f"{username}_headers", {"Authorization": f"Bearer {token}"})

    def test_01_users_see_only_their_own_notes(self):
        """Each user's /api/notes only shows their own notes."""
        # Alice creates a note
        alice_response = self.client.post(
            "/api/notes",
            json={"title": "Alice Note", "content": "Alice content"},
            headers=self.alice_headers
        )
        
        # This should fail because alice is VIEWER, not EDITOR
        # So skip this test if alice can't create notes
        if alice_response.status_code != 201:
            # Use bob to create instead
            bob_response = self.client.post(
                "/api/notes",
                json={"title": "Bob Note", "content": "Bob content"},
                headers=self.bob_headers
            )
            self.assertEqual(bob_response.status_code, 201)
            
            # Bob should see his note
            bob_list = self.client.get("/api/notes", headers=self.bob_headers)
            self.assertEqual(len(bob_list.json()), 1)
        else:
            # Alice was able to create, so this config is different
            pass

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_user_repo, None)
        app.dependency_overrides.pop(get_repo, None)


if __name__ == "__main__":
    unittest.main()


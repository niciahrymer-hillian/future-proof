#!/usr/bin/env python3
"""
TDD tests for Option D: Admin API endpoints.

Covers:
  GET  /admin/users          — list all users (ADMIN only)
  POST /admin/users          — create a user (ADMIN only)
  GET  /admin/users/{u}      — get one user (ADMIN only)
  PUT  /admin/users/{u}/role — change a user's role (ADMIN only)
  DELETE /admin/users/{u}    — deactivate a user (ADMIN only)

All endpoints require Role.ADMIN.  Requests with EDITOR or VIEWER roles return 403.
"""

import sys
import unittest
from pathlib import Path

PROJECT_PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_PYTHON_DIR))

from fastapi.testclient import TestClient
from auth import Role, InMemoryUserRepository
from note_repository import MemoryNoteRepository
from notes_api import app, get_user_repo, get_repo


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_user_repo():
    """Fresh user repo with admin, editor, and viewer accounts."""
    repo = InMemoryUserRepository()
    repo.create("admin", "admin-password", role=Role.ADMIN)
    repo.create("bob", "bob-password", role=Role.EDITOR)
    repo.create("alice", "alice-password", role=Role.VIEWER)
    return repo


_shared_note_repo = MemoryNoteRepository()


def _get_note_repo():
    return _shared_note_repo


# ---------------------------------------------------------------------------
# TestAdminListUsers
# ---------------------------------------------------------------------------

class TestAdminListUsers(unittest.TestCase):
    """GET /admin/users returns all users; non-admin callers are rejected."""

    @classmethod
    def setUpClass(cls):
        app.dependency_overrides[get_user_repo] = _make_user_repo
        app.dependency_overrides[get_repo] = _get_note_repo
        cls.client = TestClient(app)
        # Log in as all three roles
        for username, password in [("admin", "admin-password"), ("bob", "bob-password"), ("alice", "alice-password")]:
            r = cls.client.post("/auth/login", json={"username": username, "password": password})
            token = r.json()["access_token"]
            setattr(cls, f"{username}_headers", {"Authorization": f"Bearer {token}"})

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_user_repo, None)
        app.dependency_overrides.pop(get_repo, None)

    def test_admin_can_list_users(self):
        """ADMIN GET /admin/users returns a list of user objects."""
        r = self.client.get("/admin/users", headers=self.admin_headers)
        self.assertEqual(r.status_code, 200)
        users = r.json()
        self.assertIsInstance(users, list)
        usernames = [u["username"] for u in users]
        self.assertIn("admin", usernames)
        self.assertIn("bob", usernames)

    def test_editor_cannot_list_users(self):
        """EDITOR GET /admin/users returns 403."""
        r = self.client.get("/admin/users", headers=self.bob_headers)
        self.assertEqual(r.status_code, 403)

    def test_viewer_cannot_list_users(self):
        """VIEWER GET /admin/users returns 403."""
        r = self.client.get("/admin/users", headers=self.alice_headers)
        self.assertEqual(r.status_code, 403)

    def test_unauthenticated_cannot_list_users(self):
        """No auth header returns 401."""
        r = self.client.get("/admin/users")
        self.assertEqual(r.status_code, 401)


# ---------------------------------------------------------------------------
# TestAdminCreateUser
# ---------------------------------------------------------------------------

class TestAdminCreateUser(unittest.TestCase):
    """POST /admin/users creates a new user (ADMIN only)."""

    @classmethod
    def setUpClass(cls):
        app.dependency_overrides[get_user_repo] = _make_user_repo
        app.dependency_overrides[get_repo] = _get_note_repo
        cls.client = TestClient(app)
        r = cls.client.post("/auth/login", json={"username": "admin", "password": "admin-password"})
        cls.admin_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r2 = cls.client.post("/auth/login", json={"username": "bob", "password": "bob-password"})
        cls.bob_headers = {"Authorization": f"Bearer {r2.json()['access_token']}"}

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_user_repo, None)
        app.dependency_overrides.pop(get_repo, None)

    def test_admin_creates_new_user(self):
        """POST /admin/users with valid data returns 201 and user info."""
        r = self.client.post(
            "/admin/users",
            json={"username": "carol", "password": "carol-password", "role": Role.VIEWER},
            headers=self.admin_headers,
        )
        self.assertEqual(r.status_code, 201)
        data = r.json()
        self.assertEqual(data["username"], "carol")
        self.assertEqual(data["role"], Role.VIEWER)

    def test_admin_cannot_create_duplicate_user(self):
        """POST /admin/users with existing username returns 409 Conflict."""
        r = self.client.post(
            "/admin/users",
            json={"username": "alice", "password": "anything", "role": Role.VIEWER},
            headers=self.admin_headers,
        )
        self.assertEqual(r.status_code, 409)

    def test_editor_cannot_create_user(self):
        """EDITOR POST /admin/users returns 403."""
        r = self.client.post(
            "/admin/users",
            json={"username": "new", "password": "new-password", "role": Role.VIEWER},
            headers=self.bob_headers,
        )
        self.assertEqual(r.status_code, 403)


# ---------------------------------------------------------------------------
# TestAdminGetUser
# ---------------------------------------------------------------------------

class TestAdminGetUser(unittest.TestCase):
    """GET /admin/users/{username} returns one user (ADMIN only)."""

    @classmethod
    def setUpClass(cls):
        app.dependency_overrides[get_user_repo] = _make_user_repo
        app.dependency_overrides[get_repo] = _get_note_repo
        cls.client = TestClient(app)
        r = cls.client.post("/auth/login", json={"username": "admin", "password": "admin-password"})
        cls.admin_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_user_repo, None)
        app.dependency_overrides.pop(get_repo, None)

    def test_admin_gets_existing_user(self):
        """GET /admin/users/bob returns bob's info."""
        r = self.client.get("/admin/users/bob", headers=self.admin_headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["username"], "bob")

    def test_admin_gets_404_for_unknown_user(self):
        """GET /admin/users/nobody returns 404."""
        r = self.client.get("/admin/users/nobody", headers=self.admin_headers)
        self.assertEqual(r.status_code, 404)


# ---------------------------------------------------------------------------
# TestAdminUpdateRole
# ---------------------------------------------------------------------------

class TestAdminUpdateRole(unittest.TestCase):
    """PUT /admin/users/{username}/role changes role (ADMIN only)."""

    @classmethod
    def setUpClass(cls):
        app.dependency_overrides[get_user_repo] = _make_user_repo
        app.dependency_overrides[get_repo] = _get_note_repo
        cls.client = TestClient(app)
        r = cls.client.post("/auth/login", json={"username": "admin", "password": "admin-password"})
        cls.admin_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r2 = cls.client.post("/auth/login", json={"username": "bob", "password": "bob-password"})
        cls.bob_headers = {"Authorization": f"Bearer {r2.json()['access_token']}"}

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_user_repo, None)
        app.dependency_overrides.pop(get_repo, None)

    def test_admin_can_change_role(self):
        """PUT /admin/users/alice/role promotes alice to EDITOR."""
        r = self.client.put(
            "/admin/users/alice/role",
            json={"role": Role.EDITOR},
            headers=self.admin_headers,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["role"], Role.EDITOR)

    def test_admin_cannot_change_to_invalid_role(self):
        """PUT /admin/users/alice/role with unknown role returns 422."""
        r = self.client.put(
            "/admin/users/alice/role",
            json={"role": "SUPERUSER"},
            headers=self.admin_headers,
        )
        self.assertIn(r.status_code, (400, 422))

    def test_editor_cannot_change_role(self):
        """EDITOR PUT /admin/users/.../role returns 403."""
        r = self.client.put(
            "/admin/users/alice/role",
            json={"role": Role.EDITOR},
            headers=self.bob_headers,
        )
        self.assertEqual(r.status_code, 403)


# ---------------------------------------------------------------------------
# TestAdminDeactivateUser
# ---------------------------------------------------------------------------

class TestAdminDeactivateUser(unittest.TestCase):
    """DELETE /admin/users/{username} deactivates the user (soft delete)."""

    @classmethod
    def setUpClass(cls):
        # Use a singleton user repo so that deactivation in one request
        # is visible to the next request (login check).
        cls._user_repo = _make_user_repo()
        app.dependency_overrides[get_user_repo] = lambda: cls._user_repo
        app.dependency_overrides[get_repo] = _get_note_repo
        cls.client = TestClient(app)
        r = cls.client.post("/auth/login", json={"username": "admin", "password": "admin-password"})
        cls.admin_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r2 = cls.client.post("/auth/login", json={"username": "bob", "password": "bob-password"})
        cls.bob_headers = {"Authorization": f"Bearer {r2.json()['access_token']}"}

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_user_repo, None)
        app.dependency_overrides.pop(get_repo, None)

    def test_admin_can_deactivate_user(self):
        """DELETE /admin/users/alice returns 200 and marks user inactive."""
        r = self.client.delete("/admin/users/alice", headers=self.admin_headers)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["username"], "alice")
        self.assertFalse(data["is_active"])

    def test_editor_cannot_deactivate_user(self):
        """EDITOR DELETE /admin/users/... returns 403."""
        r = self.client.delete("/admin/users/alice", headers=self.bob_headers)
        self.assertEqual(r.status_code, 403)

    def test_deactivated_user_cannot_login(self):
        """After deactivation, login returns 403."""
        # Deactivate alice first (may already be done by test_admin_can_deactivate_user).
        self.client.delete("/admin/users/alice", headers=self.admin_headers)
        r = self.client.post(
            "/auth/login",
            json={"username": "alice", "password": "alice-password"},
        )
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()

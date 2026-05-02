#!/usr/bin/env python3
"""
[FILE] test_admin_api_annotated_cp.py
Annotated reference copy of python/Tests/test_admin_api.py.

[PURPOSE] TDD integration coverage for Option D admin endpoints.

[ENDPOINTS COVERED]
- GET /admin/users
- POST /admin/users
- GET /admin/users/{username}
- PUT /admin/users/{username}/role
- DELETE /admin/users/{username}

[SECURITY EXPECTATION]
All admin endpoints are protected by Depends(require_role(Role.ADMIN)).
So:
- ADMIN -> success path
- EDITOR/VIEWER -> 403 Forbidden
- No auth header -> 401 Unauthorized
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
# [FIXTURES]
# ---------------------------------------------------------------------------

def _make_user_repo():
    """[FIXTURE] Fresh in-memory user repo with three roles."""
    repo = InMemoryUserRepository()
    repo.create("admin", "admin-password", role=Role.ADMIN)
    repo.create("bob", "bob-password", role=Role.EDITOR)
    repo.create("alice", "alice-password", role=Role.VIEWER)
    return repo


_shared_note_repo = MemoryNoteRepository()


def _get_note_repo():
    """[FIXTURE] Shared note repo; required by app dependencies."""
    return _shared_note_repo


# ---------------------------------------------------------------------------
# [CLASS] TestAdminListUsers
# ---------------------------------------------------------------------------

class TestAdminListUsers(unittest.TestCase):
    """[CLASS] GET /admin/users role checks and happy path."""

    @classmethod
    def setUpClass(cls):
        app.dependency_overrides[get_user_repo] = _make_user_repo
        app.dependency_overrides[get_repo] = _get_note_repo
        cls.client = TestClient(app)
        for username, password in [
            ("admin", "admin-password"),
            ("bob", "bob-password"),
            ("alice", "alice-password"),
        ]:
            r = cls.client.post("/auth/login", json={"username": username, "password": password})
            token = r.json()["access_token"]
            setattr(cls, f"{username}_headers", {"Authorization": f"Bearer {token}"})

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_user_repo, None)
        app.dependency_overrides.pop(get_repo, None)

    def test_admin_can_list_users(self):
        """[VERIFY] ADMIN can call GET /admin/users."""
        r = self.client.get("/admin/users", headers=self.admin_headers)
        self.assertEqual(r.status_code, 200)
        users = r.json()
        self.assertIsInstance(users, list)
        usernames = [u["username"] for u in users]
        self.assertIn("admin", usernames)
        self.assertIn("bob", usernames)

    def test_editor_cannot_list_users(self):
        """[SECURITY] EDITOR gets 403."""
        r = self.client.get("/admin/users", headers=self.bob_headers)
        self.assertEqual(r.status_code, 403)

    def test_viewer_cannot_list_users(self):
        """[SECURITY] VIEWER gets 403."""
        r = self.client.get("/admin/users", headers=self.alice_headers)
        self.assertEqual(r.status_code, 403)

    def test_unauthenticated_cannot_list_users(self):
        """[SECURITY] Missing token -> 401."""
        r = self.client.get("/admin/users")
        self.assertEqual(r.status_code, 401)


# ---------------------------------------------------------------------------
# [CLASS] TestAdminCreateUser
# ---------------------------------------------------------------------------

class TestAdminCreateUser(unittest.TestCase):
    """[CLASS] POST /admin/users create path + duplicate + role guard."""

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
        """[VERIFY] Valid payload returns 201 and created user fields."""
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
        """[VERIFY] Existing username returns 409."""
        r = self.client.post(
            "/admin/users",
            json={"username": "alice", "password": "anything", "role": Role.VIEWER},
            headers=self.admin_headers,
        )
        self.assertEqual(r.status_code, 409)

    def test_editor_cannot_create_user(self):
        """[SECURITY] EDITOR gets 403."""
        r = self.client.post(
            "/admin/users",
            json={"username": "new", "password": "new-password", "role": Role.VIEWER},
            headers=self.bob_headers,
        )
        self.assertEqual(r.status_code, 403)


# ---------------------------------------------------------------------------
# [CLASS] TestAdminGetUser
# ---------------------------------------------------------------------------

class TestAdminGetUser(unittest.TestCase):
    """[CLASS] GET /admin/users/{username}."""

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
        """[VERIFY] Known user returns 200."""
        r = self.client.get("/admin/users/bob", headers=self.admin_headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["username"], "bob")

    def test_admin_gets_404_for_unknown_user(self):
        """[VERIFY] Unknown user returns 404."""
        r = self.client.get("/admin/users/nobody", headers=self.admin_headers)
        self.assertEqual(r.status_code, 404)


# ---------------------------------------------------------------------------
# [CLASS] TestAdminUpdateRole
# ---------------------------------------------------------------------------

class TestAdminUpdateRole(unittest.TestCase):
    """[CLASS] PUT /admin/users/{username}/role."""

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
        """[VERIFY] ADMIN can promote/demote users."""
        r = self.client.put(
            "/admin/users/alice/role",
            json={"role": Role.EDITOR},
            headers=self.admin_headers,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["role"], Role.EDITOR)

    def test_admin_cannot_change_to_invalid_role(self):
        """[VERIFY] Unknown role returns 400/422 depending on validation path."""
        r = self.client.put(
            "/admin/users/alice/role",
            json={"role": "SUPERUSER"},
            headers=self.admin_headers,
        )
        self.assertIn(r.status_code, (400, 422))

    def test_editor_cannot_change_role(self):
        """[SECURITY] EDITOR gets 403."""
        r = self.client.put(
            "/admin/users/alice/role",
            json={"role": Role.EDITOR},
            headers=self.bob_headers,
        )
        self.assertEqual(r.status_code, 403)


# ---------------------------------------------------------------------------
# [CLASS] TestAdminDeactivateUser
# ---------------------------------------------------------------------------

class TestAdminDeactivateUser(unittest.TestCase):
    """[CLASS] DELETE /admin/users/{username} soft-deactivation."""

    @classmethod
    def setUpClass(cls):
        # [WHY singleton user repo]
        # The deactivate flow spans multiple requests:
        # 1) DELETE /admin/users/alice
        # 2) POST /auth/login for alice
        # If we used a per-request factory, request #2 would see a fresh repo and
        # deactivation would appear to be "lost". Keeping one shared repo per class
        # ensures state persists across requests inside this scenario.
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
        """[VERIFY] DELETE marks user inactive and returns account payload."""
        r = self.client.delete("/admin/users/alice", headers=self.admin_headers)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["username"], "alice")
        self.assertFalse(data["is_active"])

    def test_editor_cannot_deactivate_user(self):
        """[SECURITY] EDITOR gets 403."""
        r = self.client.delete("/admin/users/alice", headers=self.bob_headers)
        self.assertEqual(r.status_code, 403)

    def test_deactivated_user_cannot_login(self):
        """[VERIFY] Deactivated account login path returns 403."""
        self.client.delete("/admin/users/alice", headers=self.admin_headers)
        r = self.client.post(
            "/auth/login",
            json={"username": "alice", "password": "alice-password"},
        )
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()

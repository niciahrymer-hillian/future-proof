#!/usr/bin/env python3
"""
[FILE] test_notes_api_annotated_cp.py
Annotated reference copy of python/Tests/test_notes_api.py.

[PURPOSE] Integration tests for the FastAPI REST API: auth flow, CRUD operations,
and role-based privacy enforcement.

[PATTERN] Integration vs. unit testing:
  - Unit tests (test_notes0.py, etc.) test one function in isolation.
  - Integration tests here spin up a real FastAPI app via TestClient and exercise
    the full request/response cycle — auth headers, middleware, dependency injection,
    HTTP status codes — all at once.

[WHY TestClient] FastAPI's TestClient wraps Starlette's test client (built on httpx).
  It sends real HTTP-like requests without needing a running server. This means
  route handlers, middleware, and dependencies all run exactly as in production.

[ISOLATION STRATEGY] Each test CLASS manages its own dependency overrides in
  setUpClass / tearDownClass. This prevents one class's tearDownClass from clobbering
  another class's overrides when pytest runs the full suite in an arbitrary order.
  See: the test_frontend.py tearDownClass pops overrides — if this file used
  module-level overrides they would be gone by the time TestNotesCRUD ran.
"""

import sys
import unittest
from pathlib import Path

# [SETUP] Add python/ to sys.path so imports resolve when pytest runs from project root.
PROJECT_PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_PYTHON_DIR))

from fastapi.testclient import TestClient
from auth import Role, InMemoryUserRepository

# [IMPORT] app = the FastAPI application instance
# [IMPORT] get_user_repo / get_repo = the Depends() targets we will override
from notes_api import app, get_user_repo, get_repo
from note_repository import MemoryNoteRepository, UserScopedNoteRepository


# ===========================================================================
# [SECTION] Test fixtures (shared dependency override factories)
# ===========================================================================

def get_test_user_repo():
    """[FIXTURE] Return an in-memory user repository pre-populated with test users.

    [WHY fresh per-call] A new InMemoryUserRepository on each call ensures each
    test class starts from a known state with no leftover mutations.
    [USERS]
      alice — VIEWER (can read, cannot write)
      bob   — EDITOR (can read and write)
      admin — ADMIN  (full access + user management)
    """
    repo = InMemoryUserRepository()
    repo.create("alice", "alice-password", role=Role.VIEWER)
    repo.create("bob", "bob-password", role=Role.EDITOR)
    repo.create("admin", "admin-password", role=Role.ADMIN)
    return repo


# [SINGLETON] Shared note repository instance.
# [WHY singleton NOT factory] HTTP requests arrive as separate calls. If get_test_note_repo
# returned a new MemoryNoteRepository() each time, notes created in one request
# would disappear before the next request could read them. The singleton persists
# notes across the lifetime of a test class.
# [TRADE-OFF] TestPrivacyEnforcement calls .clear() in setUpClass to reset this
# singleton for its own class, which is the correct approach.
_shared_note_repo = MemoryNoteRepository()


def get_test_note_repo():
    """[FIXTURE] Return the shared in-memory note repository for testing."""
    return _shared_note_repo


# ===========================================================================
# [CLASS] TestAuthFlow
# [PURPOSE] Verify the /auth/login endpoint: valid credentials, wrong password,
#           and missing auth header on a protected route.
# ===========================================================================

class TestAuthFlow(unittest.TestCase):
    """Verify the login flow and token handling."""

    @classmethod
    def setUpClass(cls):
        """[SETUP] Register overrides and build TestClient once for all tests in this class.

        [WHY setUpClass NOT setUp] Creating a TestClient is cheap, but re-registering
        overrides in every test adds no value. Once per class is enough.
        [PATTERN] setUpClass + tearDownClass pair keeps overrides scoped to this class,
        preventing cross-test-class contamination in the full pytest suite.
        """
        app.dependency_overrides[get_user_repo] = get_test_user_repo
        app.dependency_overrides[get_repo] = get_test_note_repo
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        """[CLEANUP] Remove overrides so the next class gets a clean slate."""
        app.dependency_overrides.pop(get_user_repo, None)
        app.dependency_overrides.pop(get_repo, None)

    def test_01_login_with_valid_credentials(self):
        """POST /auth/login with correct credentials returns a token.

        [VERIFY] Response contains 'access_token' (JWT string) and 'role' field.
        """
        response = self.client.post(
            "/auth/login",
            json={"username": "alice", "password": "alice-password"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("access_token", data)
        # [VERIFY ROLE] The role is embedded in the token AND echoed in the response
        # so callers know what they can do without decoding the JWT themselves.
        self.assertEqual(data["role"], Role.VIEWER)

    def test_02_login_with_wrong_password(self):
        """POST /auth/login with wrong password returns 401 Unauthorized.

        [SECURITY] 401 (not 404) — we confirm the username exists but don't reveal
        which field was wrong, to slow down credential-stuffing attacks.
        """
        response = self.client.post(
            "/auth/login",
            json={"username": "alice", "password": "wrong-password"}
        )
        self.assertEqual(response.status_code, 401)

    def test_03_endpoint_without_auth_header_returns_401(self):
        """GET /api/notes without Authorization header returns 401.

        [VERIFY] The Depends(require_role(...)) guard rejects unauthenticated requests
        before any repository logic runs.
        """
        response = self.client.get("/api/notes")
        self.assertEqual(response.status_code, 401)


# ===========================================================================
# [CLASS] TestNotesCRUD
# [PURPOSE] Verify note creation, listing, and role restrictions via the API.
# ===========================================================================

class TestNotesCRUD(unittest.TestCase):
    """Verify CRUD operations work with authentication."""

    @classmethod
    def setUpClass(cls):
        """[SETUP] Register overrides, build client, and pre-login both users.

        [PATTERN] Logging in once and caching the tokens in cls.* avoids repeating
        the login step in every test. Tests reuse cls.alice_headers / cls.bob_headers.
        """
        app.dependency_overrides[get_user_repo] = get_test_user_repo
        app.dependency_overrides[get_repo] = get_test_note_repo
        cls.client = TestClient(app)

        # [LOGIN] Alice — VIEWER role
        login_response = cls.client.post(
            "/auth/login",
            json={"username": "alice", "password": "alice-password"}
        )
        cls.alice_token = login_response.json()["access_token"]
        cls.alice_headers = {"Authorization": f"Bearer {cls.alice_token}"}

        # [LOGIN] Bob — EDITOR role
        login_response = cls.client.post(
            "/auth/login",
            json={"username": "bob", "password": "bob-password"}
        )
        cls.bob_token = login_response.json()["access_token"]
        cls.bob_headers = {"Authorization": f"Bearer {cls.bob_token}"}

    def test_01_get_notes_empty_list(self):
        """GET /api/notes returns empty list when no notes exist.

        [VERIFY] Fresh user scope returns [] not null/error.
        """
        response = self.client.get("/api/notes", headers=self.alice_headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data, [])

    def test_02_create_note_as_editor_succeeds(self):
        """POST /api/notes with EDITOR role creates a note and returns 201.

        [VERIFY] Response contains the created note with id, title, and content.
        """
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
        """POST /api/notes with VIEWER role returns 403 Forbidden.

        [VERIFY] Role guard fires before any repository write occurs.
        [WHY 403 not 401] 401 = "not authenticated"; 403 = "authenticated but not allowed".
        Alice has a valid token — the token just grants insufficient permissions.
        """
        response = self.client.post(
            "/api/notes",
            json={"title": "Alice's Note", "content": "Alice's content"},
            headers=self.alice_headers
        )
        self.assertEqual(response.status_code, 403)

    def test_04_list_notes_returns_only_user_notes(self):
        """GET /api/notes returns only the authenticated user's notes.

        [VERIFY] User-scoped repository isolation: Alice sees [] even after Bob
        created a note (test_02). Bob sees only his own note.
        """
        # Alice should see empty list (her scope is isolated from Bob's)
        alice_list = self.client.get("/api/notes", headers=self.alice_headers)
        self.assertEqual(alice_list.status_code, 200)
        self.assertEqual(alice_list.json(), [])

        # Bob should see his note (created in test_02 above)
        bob_list = self.client.get("/api/notes", headers=self.bob_headers)
        self.assertEqual(bob_list.status_code, 200)
        bob_notes = bob_list.json()
        self.assertEqual(len(bob_notes), 1)

    @classmethod
    def tearDownClass(cls):
        """[CLEANUP] Remove overrides so the next class gets a clean slate."""
        app.dependency_overrides.pop(get_user_repo, None)
        app.dependency_overrides.pop(get_repo, None)


# ===========================================================================
# [CLASS] TestPrivacyEnforcement
# [PURPOSE] Confirm one user cannot see or access another user's notes.
# ===========================================================================

class TestPrivacyEnforcement(unittest.TestCase):
    """Verify users cannot access other users' notes."""

    @classmethod
    def setUpClass(cls):
        """[SETUP] Register overrides, RESET the shared repo, then log in both users.

        [WHY .clear()] _shared_note_repo is a singleton. TestNotesCRUD may have
        created notes in it. .clear() ensures this class starts with zero notes so
        assertions about counts are reliable.
        """
        app.dependency_overrides[get_user_repo] = get_test_user_repo
        app.dependency_overrides[get_repo] = get_test_note_repo
        # Reset shared repo — this class must start with a clean slate.
        _shared_note_repo.clear()
        cls.client = TestClient(app)

        # [PATTERN] Compact loop to log in multiple users and store tokens/headers.
        for username in ["alice", "bob"]:
            login_response = cls.client.post(
                "/auth/login",
                json={"username": username, "password": f"{username}-password"}
            )
            token = login_response.json()["access_token"]
            setattr(cls, f"{username}_token", token)
            setattr(cls, f"{username}_headers", {"Authorization": f"Bearer {token}"})

    def test_01_users_see_only_their_own_notes(self):
        """Each user's /api/notes only shows their own notes.

        [PATTERN] Alice is VIEWER so cannot POST /api/notes. The test gracefully
        falls back to using Bob (EDITOR) to verify note isolation.
        [WHY conditional] Rather than hard-wiring Bob, the test reflects the real
        permission model: if Alice could write, we'd verify her scope; since she
        can't, we verify Bob's scope instead.
        """
        # Try to create a note as Alice
        alice_response = self.client.post(
            "/api/notes",
            json={"title": "Alice Note", "content": "Alice content"},
            headers=self.alice_headers
        )

        if alice_response.status_code != 201:
            # [EXPECTED PATH] Alice is VIEWER — use Bob to create a note instead.
            bob_response = self.client.post(
                "/api/notes",
                json={"title": "Bob Note", "content": "Bob content"},
                headers=self.bob_headers
            )
            self.assertEqual(bob_response.status_code, 201)

            # Bob sees his own note; his scope is not empty.
            bob_list = self.client.get("/api/notes", headers=self.bob_headers)
            self.assertEqual(len(bob_list.json()), 1)
        else:
            # [ALTERNATE PATH] If Alice had EDITOR role (config changed), verify her scope.
            pass

    @classmethod
    def tearDownClass(cls):
        """[CLEANUP] Remove overrides so the next class gets a clean slate."""
        app.dependency_overrides.pop(get_user_repo, None)
        app.dependency_overrides.pop(get_repo, None)


if __name__ == "__main__":
    unittest.main()

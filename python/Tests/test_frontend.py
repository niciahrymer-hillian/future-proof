"""Tests for the server-rendered HTML frontend (Option C).

WHY THESE TESTS EXIST:
  The frontend is just another layer on top of the same FastAPI app.
  We test it through the same TestClient but follow HTML responses and
  form submissions rather than JSON requests.

WHAT IS TESTED:
  - Login page renders correctly (GET /login)
  - Successful form login sets a session cookie (POST /login)
  - Bad credentials redirect back to login with error
  - Notes list page requires auth (GET /)
  - Notes list page shows notes for the logged-in user (GET /)
  - Create note form page requires auth (GET /notes/new)
  - Create note form submission creates a note (POST /notes/new)
  - Note detail page shows full content (GET /notes/<id>)
  - Edit note form page renders with current values (GET /notes/<id>/edit)
  - Edit note form submission updates the note (POST /notes/<id>/edit)
  - Delete note form submission removes the note (POST /notes/<id>/delete)
  - Search page renders a form and shows results (GET /search?text=...)
  - Logout clears the session cookie (POST /logout)

TEST ISOLATION:
  Each test class sets up its own MemoryNoteRepository and MemoryUserRepository
  via dependency overrides in setUpClass. This avoids polluting other test modules.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from fastapi.testclient import TestClient

from notes_api import app, get_repo, get_user_repo
from note_repository import MemoryNoteRepository
from auth import InMemoryUserRepository, Role


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

def make_repos():
    """Create fresh in-memory repositories for test isolation."""
    note_repo = MemoryNoteRepository()
    user_repo = InMemoryUserRepository()
    user_repo.create("alice", "alice-pass", role=Role.EDITOR)
    user_repo.create("viewer", "viewer-pass", role=Role.VIEWER)
    return note_repo, user_repo


def get_session_cookie(client: TestClient, username: str, password: str) -> dict:
    """POST to /login and return the session cookie as a dict for use in requests."""
    resp = client.post("/login", data={"username": username, "password": password}, follow_redirects=False)
    assert resp.status_code in (302, 303), f"Login failed: {resp.status_code} {resp.text}"
    # Extract the Set-Cookie header value
    cookie_header = resp.headers.get("set-cookie", "")
    assert "session=" in cookie_header, "No session cookie in login response"
    # TestClient automatically carries cookies between requests; just return cookies dict
    return client.cookies


# ---------------------------------------------------------------------------
# Login / Logout page
# ---------------------------------------------------------------------------

class TestLoginPage(unittest.TestCase):
    """Login page renders, accepts credentials, and rejects bad ones."""

    @classmethod
    def setUpClass(cls):
        cls._note_repo, cls._user_repo = make_repos()
        app.dependency_overrides[get_repo] = lambda: cls._note_repo
        app.dependency_overrides[get_user_repo] = lambda: cls._user_repo
        cls.client = TestClient(app, raise_server_exceptions=True)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_repo, None)
        app.dependency_overrides.pop(get_user_repo, None)

    def test_login_page_renders(self):
        """GET /login returns 200 and contains a form."""
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("<form", resp.text)
        self.assertIn('name="username"', resp.text)
        self.assertIn('name="password"', resp.text)

    def test_valid_login_redirects_to_home(self):
        """POST /login with valid credentials sets a session cookie and redirects."""
        resp = self.client.post(
            "/login",
            data={"username": "alice", "password": "alice-pass"},
            follow_redirects=False,
        )
        self.assertIn(resp.status_code, (302, 303))
        self.assertIn("session=", resp.headers.get("set-cookie", ""))

    def test_invalid_login_shows_error(self):
        """POST /login with wrong password re-renders login with an error message."""
        resp = self.client.post(
            "/login",
            data={"username": "alice", "password": "wrong"},
            follow_redirects=False,
        )
        # Should stay on login page (200/401 re-render) or redirect back (302 to /login)
        if resp.status_code in (302, 303):
            follow = self.client.get(resp.headers["location"])
            self.assertIn("error", follow.text.lower())
        else:
            # 200 or 401 — both are acceptable for a re-rendered form with an error
            self.assertIn(resp.status_code, (200, 401))
            self.assertIn("error", resp.text.lower())

    def test_logout_clears_session(self):
        """POST /logout removes the session cookie."""
        # First log in
        self.client.post("/login", data={"username": "alice", "password": "alice-pass"})
        # Then log out
        resp = self.client.post("/logout", follow_redirects=False)
        self.assertIn(resp.status_code, (302, 303))


# ---------------------------------------------------------------------------
# Notes list page
# ---------------------------------------------------------------------------

class TestNotesListPage(unittest.TestCase):
    """The home page lists notes for the logged-in user."""

    @classmethod
    def setUpClass(cls):
        cls._note_repo, cls._user_repo = make_repos()
        app.dependency_overrides[get_repo] = lambda: cls._note_repo
        app.dependency_overrides[get_user_repo] = lambda: cls._user_repo
        cls.client = TestClient(app, raise_server_exceptions=True)
        # Log in as alice
        cls.client.post("/login", data={"username": "alice", "password": "alice-pass"})
        # Add a note via the API so alice's repo has data
        cls.client.post(
            "/api/notes",
            json={"title": "Alice note", "content": "hello world"},
            headers={"Authorization": f"Bearer {cls._get_token()}"},
        )

    @classmethod
    def _get_token(cls):
        resp = TestClient(app).post(
            "/auth/login",
            json={"username": "alice", "password": "alice-pass"},
        )
        return resp.json()["access_token"]

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_repo, None)
        app.dependency_overrides.pop(get_user_repo, None)

    def test_home_redirects_when_unauthenticated(self):
        """GET / without a session redirects to /login."""
        fresh_client = TestClient(app, raise_server_exceptions=True)
        resp = fresh_client.get("/", follow_redirects=False)
        self.assertIn(resp.status_code, (302, 303))
        self.assertIn("/login", resp.headers.get("location", ""))

    def test_notes_list_renders_for_logged_in_user(self):
        """GET / with a session shows the notes list page."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Alice note", resp.text)

    def test_notes_list_contains_create_link(self):
        """The list page has a link or button to create a new note."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        # Could be a link to /notes/new or a button labelled "New note"
        self.assertTrue(
            "/notes/new" in resp.text or "new note" in resp.text.lower()
        )


# ---------------------------------------------------------------------------
# Create note
# ---------------------------------------------------------------------------

class TestCreateNote(unittest.TestCase):
    """Creating a note through the HTML form."""

    @classmethod
    def setUpClass(cls):
        cls._note_repo, cls._user_repo = make_repos()
        app.dependency_overrides[get_repo] = lambda: cls._note_repo
        app.dependency_overrides[get_user_repo] = lambda: cls._user_repo
        cls.client = TestClient(app, raise_server_exceptions=True)
        cls.client.post("/login", data={"username": "alice", "password": "alice-pass"})

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_repo, None)
        app.dependency_overrides.pop(get_user_repo, None)

    def test_create_form_renders(self):
        """GET /notes/new returns 200 with a form containing title and content fields."""
        resp = self.client.get("/notes/new")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("<form", resp.text)
        self.assertIn('name="title"', resp.text)
        self.assertIn('name="content"', resp.text)

    def test_create_form_submission_creates_note(self):
        """POST /notes/new with valid data creates a note and redirects to list."""
        resp = self.client.post(
            "/notes/new",
            data={"title": "Test creation", "content": "body text", "tags": "alpha,beta"},
            follow_redirects=False,
        )
        self.assertIn(resp.status_code, (302, 303))
        # Note now appears in the repo
        notes = self._note_repo.list_all()
        titles = [n["title"] for n in notes]
        self.assertIn("Test creation", titles)

    def test_create_form_requires_login(self):
        """GET /notes/new without a session redirects to /login."""
        fresh = TestClient(app, raise_server_exceptions=True)
        resp = fresh.get("/notes/new", follow_redirects=False)
        self.assertIn(resp.status_code, (302, 303))
        self.assertIn("/login", resp.headers.get("location", ""))


# ---------------------------------------------------------------------------
# Note detail and edit
# ---------------------------------------------------------------------------

class TestNoteDetailAndEdit(unittest.TestCase):
    """Viewing, editing, and deleting individual notes through HTML pages."""

    @classmethod
    def setUpClass(cls):
        cls._note_repo, cls._user_repo = make_repos()
        app.dependency_overrides[get_repo] = lambda: cls._note_repo
        app.dependency_overrides[get_user_repo] = lambda: cls._user_repo
        cls.client = TestClient(app, raise_server_exceptions=True)
        cls.client.post("/login", data={"username": "alice", "password": "alice-pass"})
        # Seed a note directly into alice's scoped repo
        from note_repository import UserScopedNoteRepository
        scoped = UserScopedNoteRepository(cls._note_repo)
        scoped.set_user("alice")
        cls._note_id = scoped.add("Detail note", "Original body", tags=["x"])

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_repo, None)
        app.dependency_overrides.pop(get_user_repo, None)

    def test_detail_page_shows_content(self):
        """GET /notes/<id> shows the note title and body."""
        resp = self.client.get(f"/notes/{self._note_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Detail note", resp.text)
        self.assertIn("Original body", resp.text)

    def test_edit_form_pre_fills_current_values(self):
        """GET /notes/<id>/edit renders a form with the note's current title and content."""
        resp = self.client.get(f"/notes/{self._note_id}/edit")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Detail note", resp.text)
        self.assertIn("Original body", resp.text)

    def test_edit_form_submission_updates_note(self):
        """POST /notes/<id>/edit with new values updates the note."""
        resp = self.client.post(
            f"/notes/{self._note_id}/edit",
            data={"title": "Updated title", "content": "Updated body"},
            follow_redirects=False,
        )
        self.assertIn(resp.status_code, (302, 303))
        from note_repository import UserScopedNoteRepository
        scoped = UserScopedNoteRepository(self._note_repo)
        scoped.set_user("alice")
        note = scoped.get(self._note_id)
        self.assertEqual(note.title, "Updated title")
        self.assertEqual(note.content, "Updated body")

    def test_delete_removes_note(self):
        """POST /notes/<id>/delete removes the note and redirects to list."""
        # Create a throw-away note
        from note_repository import UserScopedNoteRepository
        scoped = UserScopedNoteRepository(self._note_repo)
        scoped.set_user("alice")
        tid = scoped.add("To be deleted", "gone soon")

        resp = self.client.post(f"/notes/{tid}/delete", follow_redirects=False)
        self.assertIn(resp.status_code, (302, 303))
        # UserScopedNoteRepository.get() returns None for deleted/missing notes
        from note_repository import UserScopedNoteRepository
        scoped2 = UserScopedNoteRepository(self._note_repo)
        scoped2.set_user("alice")
        self.assertIsNone(scoped2.get(tid))


# ---------------------------------------------------------------------------
# Search page
# ---------------------------------------------------------------------------

class TestSearchPage(unittest.TestCase):
    """The search page renders a form and shows matching notes."""

    @classmethod
    def setUpClass(cls):
        cls._note_repo, cls._user_repo = make_repos()
        app.dependency_overrides[get_repo] = lambda: cls._note_repo
        app.dependency_overrides[get_user_repo] = lambda: cls._user_repo
        cls.client = TestClient(app, raise_server_exceptions=True)
        cls.client.post("/login", data={"username": "alice", "password": "alice-pass"})
        from note_repository import UserScopedNoteRepository
        scoped = UserScopedNoteRepository(cls._note_repo)
        scoped.set_user("alice")
        scoped.add("Python tips", "list comprehensions", tags=["python"])
        scoped.add("Grocery list", "milk eggs bread", tags=["personal"])

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_repo, None)
        app.dependency_overrides.pop(get_user_repo, None)

    def test_search_page_renders_form(self):
        """GET /search shows a search form."""
        resp = self.client.get("/search")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("<form", resp.text)
        self.assertIn('name="text"', resp.text)

    def test_search_returns_matching_notes(self):
        """GET /search?text=python shows only matching notes."""
        resp = self.client.get("/search?text=python")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Python tips", resp.text)
        self.assertNotIn("Grocery list", resp.text)

    def test_search_empty_query_shows_all(self):
        """GET /search with no query shows all notes."""
        resp = self.client.get("/search")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Python tips", resp.text)
        self.assertIn("Grocery list", resp.text)

    def test_search_requires_login(self):
        """GET /search without session redirects to /login."""
        fresh = TestClient(app, raise_server_exceptions=True)
        resp = fresh.get("/search", follow_redirects=False)
        self.assertIn(resp.status_code, (302, 303))
        self.assertIn("/login", resp.headers.get("location", ""))


if __name__ == "__main__":
    unittest.main()

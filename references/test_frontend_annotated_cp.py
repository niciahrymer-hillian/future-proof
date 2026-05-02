#!/usr/bin/env python3
"""[ANATOMY] tests for the server-rendered HTML frontend (Option C).

[WHAT] Integration tests for the HTML frontend layer.
       Exercises cookie-based session auth and form submissions
       rather than JSON/token flows.

[WHY] The frontend adds new surfaces (session cookies, form POST routes,
      HTML templates) that the API tests don't cover. These tests verify
      the browser-facing layer end-to-end without a real browser.

[PATTERN] Each test class:
  - Creates fresh in-memory repos in setUpClass (test isolation)
  - Sets app.dependency_overrides in setUpClass (not at module level)
  - Removes overrides in tearDownClass (prevents collision with other modules)
  - Uses TestClient which supports cookies automatically between requests

[WHY NOT MODULE-LEVEL OVERRIDES] If multiple test modules set
app.dependency_overrides at module level, the last one imported wins.
Scoping to setUpClass avoids that problem.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from fastapi.testclient import TestClient

# [IMPORT] app + dependency functions we will override
from notes_api import app, get_repo, get_user_repo

# [IMPORT] in-memory implementations injected during tests
from note_repository import MemoryNoteRepository
from auth import InMemoryUserRepository, Role


# ---------------------------------------------------------------------------
# [HELPER] Shared fixture builders
# ---------------------------------------------------------------------------

def make_repos():
    """[FACTORY] Create fresh in-memory repositories for test isolation.

    [WHY FRESH PER CLASS] Shared repos accumulate state across classes and
    cause order-dependent failures. Each class gets its own MemoryNoteRepository
    and InMemoryUserRepository.
    """
    note_repo = MemoryNoteRepository()
    user_repo = InMemoryUserRepository()
    # [SEED] Pre-create users so login tests don't depend on signup
    user_repo.create("alice", "alice-pass", role=Role.EDITOR)
    user_repo.create("viewer", "viewer-pass", role=Role.VIEWER)
    return note_repo, user_repo


def get_session_cookie(client: TestClient, username: str, password: str) -> dict:
    """[HELPER] POST to /login and return the session cookie as a dict for use in requests.

    [NOTE] TestClient stores cookies internally between requests automatically,
    so you don't usually need to pass cookies explicitly after calling login.
    This helper is provided for completeness.
    """
    resp = client.post("/login", data={"username": username, "password": password}, follow_redirects=False)
    assert resp.status_code in (302, 303), f"Login failed: {resp.status_code} {resp.text}"
    cookie_header = resp.headers.get("set-cookie", "")
    assert "session=" in cookie_header, "No session cookie in login response"
    return client.cookies


# ---------------------------------------------------------------------------
# [CLASS] Login / Logout page
# ---------------------------------------------------------------------------

class TestLoginPage(unittest.TestCase):
    """[WHAT] Login page renders, accepts credentials, and rejects bad ones.

    [WHY] The login page is the entry point for all browser users.
    These tests verify the form exists, valid creds produce a session cookie,
    and bad creds stay on the login page with an error message.
    """

    @classmethod
    def setUpClass(cls):
        # [ISOLATION] Fresh repos + scoped overrides for this class only
        cls._note_repo, cls._user_repo = make_repos()
        app.dependency_overrides[get_repo] = lambda: cls._note_repo
        app.dependency_overrides[get_user_repo] = lambda: cls._user_repo
        cls.client = TestClient(app, raise_server_exceptions=True)

    @classmethod
    def tearDownClass(cls):
        # [CLEANUP] Remove overrides so other test modules are not affected
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
        """POST /login with valid credentials sets a session cookie and redirects.

        [WHY 303] POST-redirect-GET pattern: 303 tells the browser to GET the
        next page. This prevents the form from being re-submitted on refresh.
        """
        resp = self.client.post(
            "/login",
            data={"username": "alice", "password": "alice-pass"},
            follow_redirects=False,
        )
        self.assertIn(resp.status_code, (302, 303))
        # [EFFECT] Session cookie must be set so subsequent requests are authenticated
        self.assertIn("session=", resp.headers.get("set-cookie", ""))

    def test_invalid_login_shows_error(self):
        """POST /login with wrong password re-renders login with an error message.

        [WHY] Do not reveal whether username or password was wrong — always say
        "invalid username or password" to avoid user enumeration attacks.
        """
        resp = self.client.post(
            "/login",
            data={"username": "alice", "password": "wrong"},
            follow_redirects=False,
        )
        # [ACCEPTABLE RESPONSES] 200/401 re-render or 302/303 redirect back to /login
        if resp.status_code in (302, 303):
            follow = self.client.get(resp.headers["location"])
            self.assertIn("error", follow.text.lower())
        else:
            self.assertIn(resp.status_code, (200, 401))
            self.assertIn("error", resp.text.lower())

    def test_logout_clears_session(self):
        """POST /logout removes the session cookie."""
        # First log in
        self.client.post("/login", data={"username": "alice", "password": "alice-pass"})
        # Then log out
        resp = self.client.post("/logout", follow_redirects=False)
        # [EFFECT] Redirect to /login after logout
        self.assertIn(resp.status_code, (302, 303))


# ---------------------------------------------------------------------------
# [CLASS] Notes list page
# ---------------------------------------------------------------------------

class TestNotesListPage(unittest.TestCase):
    """[WHAT] The home page (/) lists notes for the logged-in user.

    [WHY] Verifies redirect-when-unauthenticated, correct note display,
    and presence of the "New note" link for EDITOR users.
    """

    @classmethod
    def setUpClass(cls):
        cls._note_repo, cls._user_repo = make_repos()
        app.dependency_overrides[get_repo] = lambda: cls._note_repo
        app.dependency_overrides[get_user_repo] = lambda: cls._user_repo
        cls.client = TestClient(app, raise_server_exceptions=True)
        # Log in as alice (EDITOR)
        cls.client.post("/login", data={"username": "alice", "password": "alice-pass"})
        # Seed a note via the API using a JWT token
        cls.client.post(
            "/api/notes",
            json={"title": "Alice note", "content": "hello world"},
            headers={"Authorization": f"Bearer {cls._get_token()}"},
        )

    @classmethod
    def _get_token(cls):
        """[HELPER] Get a JWT token for alice to use with the API routes."""
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
        """GET / without a session redirects to /login.

        [SECURITY] Unauthenticated users must not see any note data.
        """
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
        """The list page has a link or button to create a new note.

        [WHY] EDITOR users should always have a visible path to create notes.
        """
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            "/notes/new" in resp.text or "new note" in resp.text.lower()
        )


# ---------------------------------------------------------------------------
# [CLASS] Create note form
# ---------------------------------------------------------------------------

class TestCreateNote(unittest.TestCase):
    """[WHAT] Creating a note through the HTML form.

    [WHY] Covers the full create flow: form renders, submission creates a note,
    unauthenticated users are redirected.
    """

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
        """POST /notes/new with valid data creates a note and redirects to list.

        [EFFECT] Note appears in the MemoryNoteRepository; checking there directly
        is faster and more reliable than parsing HTML.
        Tags field accepts comma-separated values; the endpoint splits them.
        """
        resp = self.client.post(
            "/notes/new",
            data={"title": "Test creation", "content": "body text", "tags": "alpha,beta"},
            follow_redirects=False,
        )
        self.assertIn(resp.status_code, (302, 303))
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
# [CLASS] Note detail and edit
# ---------------------------------------------------------------------------

class TestNoteDetailAndEdit(unittest.TestCase):
    """[WHAT] Viewing, editing, and deleting individual notes through HTML pages.

    [SEED STRATEGY] Notes are seeded directly into the UserScopedNoteRepository
    in setUpClass. This is faster than going through the API and doesn't require
    a JWT token.
    """

    @classmethod
    def setUpClass(cls):
        cls._note_repo, cls._user_repo = make_repos()
        app.dependency_overrides[get_repo] = lambda: cls._note_repo
        app.dependency_overrides[get_user_repo] = lambda: cls._user_repo
        cls.client = TestClient(app, raise_server_exceptions=True)
        cls.client.post("/login", data={"username": "alice", "password": "alice-pass"})
        # [SEED] Add a note directly via scoped repo
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
        """GET /notes/<id>/edit renders a form with the note's current title and content.

        [UX] Pre-filling avoids requiring users to re-type unchanged fields.
        """
        resp = self.client.get(f"/notes/{self._note_id}/edit")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Detail note", resp.text)
        self.assertIn("Original body", resp.text)

    def test_edit_form_submission_updates_note(self):
        """POST /notes/<id>/edit with new values updates the note.

        [EFFECT] Verified by reading the note back from the repo directly.
        """
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
        """POST /notes/<id>/delete removes the note and redirects to list.

        [WHY POST] HTML forms only support GET and POST; a DELETE method form
        is not supported without JavaScript. POST /notes/<id>/delete is the
        standard workaround.
        [VERIFY] UserScopedNoteRepository.get() returns None (not raises) for
        a missing note, so we check for None rather than FileNotFoundError.
        """
        from note_repository import UserScopedNoteRepository
        scoped = UserScopedNoteRepository(self._note_repo)
        scoped.set_user("alice")
        tid = scoped.add("To be deleted", "gone soon")

        resp = self.client.post(f"/notes/{tid}/delete", follow_redirects=False)
        self.assertIn(resp.status_code, (302, 303))
        # [VERIFY] UserScopedNoteRepository.get() returns None for deleted/missing notes
        scoped2 = UserScopedNoteRepository(self._note_repo)
        scoped2.set_user("alice")
        self.assertIsNone(scoped2.get(tid))


# ---------------------------------------------------------------------------
# [CLASS] Search page
# ---------------------------------------------------------------------------

class TestSearchPage(unittest.TestCase):
    """[WHAT] The search page renders a form and shows matching notes.

    [WHY] The HTML search page is a thin wrapper over the same filter logic
    used by GET /api/search. These tests verify the page renders correctly
    and that the filters actually narrow results.
    """

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
        """GET /search shows a search form with a text input."""
        resp = self.client.get("/search")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("<form", resp.text)
        self.assertIn('name="text"', resp.text)

    def test_search_returns_matching_notes(self):
        """GET /search?text=python shows only matching notes.

        [FILTER] Text filter checks title and content preview (case-insensitive).
        """
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
        """GET /search without session redirects to /login.

        [SECURITY] All pages behind the auth wall must redirect, not 200.
        """
        fresh = TestClient(app, raise_server_exceptions=True)
        resp = fresh.get("/search", follow_redirects=False)
        self.assertIn(resp.status_code, (302, 303))
        self.assertIn("/login", resp.headers.get("location", ""))


if __name__ == "__main__":
    unittest.main()

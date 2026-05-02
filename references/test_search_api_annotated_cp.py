#!/usr/bin/env python3
"""
[ANATOMY: PURPOSE]
  Annotated reference copy of python/Tests/test_search_api.py.
  Labels explain WHY each decision was made, not just what the code does.

  This file uses the same [ANATOMY] bracket label system as the other
  annotated copies in references/:
    [CLASS]      — class declaration context
    [METHOD]     — method / function declaration
    [VARIABLE]   — local variable or assignment
    [WHY]        — rationale for a design choice
    [EFFECT]     — observable outcome of a code block
    [SECURITY]   — security-relevant note
    [PATTERN]    — a reusable design pattern in use

[ANATOMY: KEY CONCEPTS]
  1. TDD ORDER: tests were written before the endpoint was updated.
     Writing tests first forces you to define the contract (input/output shape,
     status codes, error cases) before you write the code that satisfies it.
     Effect: the implementation can't "accidentally" pass tests by being shaped
     around what it already does.

  2. DEPENDENCY OVERRIDES: FastAPI's dependency injection (Depends()) makes
     swapping dependencies in tests trivial. Instead of real files or a real
     user database, we inject:
       - InMemoryUserRepository   — users live only for the test run
       - MemoryNoteRepository     — notes live only for the test run
     Effect: tests are fast, isolated, and never touch disk.

  3. SCOPED OVERRIDES vs MODULE-LEVEL: overrides are set in setUpClass (not
     at module level) so this file doesn't clobber other test modules that
     also override app.dependency_overrides when the full suite runs together.

  4. SHARED SINGLETON: the repo is a module-level singleton.
     If get_test_note_repo() returned a new MemoryNoteRepository() every call,
     notes would vanish between requests. One shared instance survives across
     multiple TestClient calls.

  5. FILTER INDEPENDENCE: each filter (text, tag, date) is tested in isolation
     before being tested in combination. This localises the root cause when a
     test fails — you know exactly which filter broke.
"""

import sys
import unittest
from pathlib import Path

# [VARIABLE] PROJECT_PYTHON_DIR — ensures imports resolve to the project's
# python/ directory regardless of where pytest is invoked from.
PROJECT_PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_PYTHON_DIR))

from fastapi.testclient import TestClient
from auth import Role, InMemoryUserRepository
from notes_api import app, get_user_repo, get_repo
from note_repository import MemoryNoteRepository


# ---------------------------------------------------------------------------
# [ANATOMY: TEST FIXTURES]
# ---------------------------------------------------------------------------

# [FUNCTION] get_test_user_repo
# [WHY] Provides two users covering the two relevant role tiers:
#   - VIEWER: read-only; confirms search is accessible to read-only users
#   - EDITOR: can create notes; needed for seeding test data in setUpClass
# [EFFECT] Every test in this module sees exactly these two users.
def get_test_user_repo():
    repo = InMemoryUserRepository()
    repo.create("viewer", "viewer-password", role=Role.VIEWER)
    repo.create("editor", "editor-password", role=Role.EDITOR)
    return repo


# [VARIABLE] _shared_note_repo — module-level singleton.
# [WHY] FastAPI calls the dependency function once per request.
# If we returned a new MemoryNoteRepository() on every call, notes created
# in one request would vanish by the next. The singleton keeps all notes
# alive for the entire test session.
_shared_note_repo = MemoryNoteRepository()


def get_test_note_repo():
    return _shared_note_repo


# ---------------------------------------------------------------------------
# [CLASS] TestSearchAPI
# ---------------------------------------------------------------------------

class TestSearchAPI(unittest.TestCase):
    """Verify GET /api/search with all supported filters.

    [WHY SINGLE CLASS] All search tests share the same seeded notes
    (created once in setUpClass), so grouping them into one class avoids
    re-creating those notes before every individual test.
    """

    @classmethod
    def setUpClass(cls):
        # [ANATOMY: SCOPED OVERRIDE]
        # Override dependencies HERE (not at module level) so this module
        # doesn't interfere with test_notes_api.py's overrides when the
        # full suite runs. Each module owns its own override window.
        app.dependency_overrides[get_user_repo] = get_test_user_repo
        app.dependency_overrides[get_repo] = get_test_note_repo

        # [WHY clear()] In case earlier modules left notes in _shared_note_repo.
        # Effect: this class always starts with exactly the notes it creates below.
        _shared_note_repo.clear()

        # [VARIABLE] cls.client — shared test client; creating it once is faster
        # than re-creating it for every test method.
        cls.client = TestClient(app)

        # ── Login ──────────────────────────────────────────────────────────
        # [VARIABLE] cls.editor_headers / cls.viewer_headers
        # [WHY] Storing headers at the class level avoids repeating the login
        # call in every test method. Every test that needs auth just uses
        # cls.editor_headers or cls.viewer_headers.
        editor_resp = cls.client.post(
            "/auth/login", json={"username": "editor", "password": "editor-password"}
        )
        viewer_resp = cls.client.post(
            "/auth/login", json={"username": "viewer", "password": "viewer-password"}
        )
        cls.editor_headers = {"Authorization": f"Bearer {editor_resp.json()['access_token']}"}
        cls.viewer_headers = {"Authorization": f"Bearer {viewer_resp.json()['access_token']}"}

        # ── Seed notes ─────────────────────────────────────────────────────
        # [WHY FOUR NOTES] Each note is designed to participate in a specific
        # filter test or to serve as a "should NOT match" control:
        #
        #   Note A: no tags, older date  → text-search hit, excluded by date filters
        #   Note B: python + ideas tags  → both tag tests and text tests
        #   Note C: ideas tag only       → single-tag match, excluded by python-tag filter
        #   Note D: unique keyword       → ensures text search is specific

        resp_a = cls.client.post(
            "/api/notes",
            json={"title": "Python Basics", "content": "Variables and loops in Python."},
            headers=cls.editor_headers,
        )
        cls.note_a_id = resp_a.json()["id"]

        resp_b = cls.client.post(
            "/api/notes",
            json={
                "title": "Python Ideas",
                "content": "Ideas for Python projects.",
                "tags": ["python", "ideas"],
            },
            headers=cls.editor_headers,
        )
        cls.note_b_id = resp_b.json()["id"]

        resp_c = cls.client.post(
            "/api/notes",
            json={
                "title": "Weekend Ideas",
                "content": "Go hiking or cycling.",
                "tags": ["ideas"],
            },
            headers=cls.editor_headers,
        )
        cls.note_c_id = resp_c.json()["id"]

        resp_d = cls.client.post(
            "/api/notes",
            json={"title": "Code Quality", "content": "Notes on refactoring legacy code."},
            headers=cls.editor_headers,
        )
        cls.note_d_id = resp_d.json()["id"]

        # [ANATOMY: DATE INJECTION]
        # [WHY] The API doesn't accept a custom modified date — notes get "now".
        # To test date range filters we need predictable timestamps. We set them
        # directly on the in-memory Note objects after creation.
        # [EFFECT] Notes A and B appear to have been modified in early 2026,
        # well before the current date, so after/before filters can distinguish them.
        for note_id, ts in [
            (cls.note_a_id, "2026-01-15T10:00:00"),
            (cls.note_b_id, "2026-02-20T10:00:00"),
        ]:
            note = _shared_note_repo.get(note_id)
            note.modified = ts
            note.created = ts

    # ── [SECTION] Response shape ───────────────────────────────────────────

    def test_01_response_has_expected_keys(self):
        """Search response includes query, filters, count, and matches keys.

        [WHY] Before checking individual filter logic, verify the response
        envelope. If the shape is wrong, every downstream assertion will fail
        with confusing KeyError messages instead of a clear contract failure.
        """
        resp = self.client.get("/api/search?text=python", headers=self.editor_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("query", data)
        self.assertIn("filters", data)
        self.assertIn("count", data)
        self.assertIn("matches", data)

    def test_02_match_objects_have_summary_fields(self):
        """Each match includes id, title, tags, created, modified, and preview.

        [WHY] Clients need more than just an ID — they need enough info to
        render a results list without making a second request per match.
        """
        resp = self.client.get("/api/search?text=python", headers=self.editor_headers)
        matches = resp.json()["matches"]
        self.assertGreater(len(matches), 0)
        for m in matches:
            for key in ("id", "title", "tags", "created", "modified", "preview"):
                self.assertIn(key, m, f"match missing key: {key}")

    # ── [SECTION] Text search ──────────────────────────────────────────────

    def test_03_text_search_returns_matching_notes(self):
        """?text=python returns notes whose title or content contains 'python'."""
        resp = self.client.get("/api/search?text=python", headers=self.editor_headers)
        ids = {m["id"] for m in resp.json()["matches"]}
        self.assertIn(self.note_a_id, ids)
        self.assertIn(self.note_b_id, ids)
        self.assertNotIn(self.note_c_id, ids)
        self.assertNotIn(self.note_d_id, ids)

    def test_04_text_search_is_case_insensitive(self):
        """?text=PYTHON matches the same notes as ?text=python.

        [WHY] Users shouldn't need to know the case of what they're searching for.
        """
        lower = {m["id"] for m in self.client.get("/api/search?text=python", headers=self.editor_headers).json()["matches"]}
        upper = {m["id"] for m in self.client.get("/api/search?text=PYTHON", headers=self.editor_headers).json()["matches"]}
        self.assertEqual(lower, upper)

    def test_05_text_search_no_matches_returns_empty_list(self):
        """?text=xyzzy returns an empty matches list (not a 404 or error).

        [WHY] No matches is a valid result, not an error.
        Returning 404 would break client code that checks for HTTP errors.
        """
        resp = self.client.get("/api/search?text=xyzzy", headers=self.editor_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["matches"], [])
        self.assertEqual(resp.json()["count"], 0)

    # ── [SECTION] Tag filtering ────────────────────────────────────────────

    def test_06_single_tag_filter(self):
        """?tag=ideas returns all notes that have the 'ideas' tag."""
        resp = self.client.get("/api/search?tag=ideas", headers=self.editor_headers)
        ids = {m["id"] for m in resp.json()["matches"]}
        self.assertIn(self.note_b_id, ids)
        self.assertIn(self.note_c_id, ids)
        self.assertNotIn(self.note_a_id, ids)
        self.assertNotIn(self.note_d_id, ids)

    def test_07_multiple_tag_filter_is_intersection(self):
        """?tag=python&tag=ideas returns only notes that have BOTH tags.

        [WHY AND SEMANTICS] Intersection (AND) is more precise than union (OR).
        A user asking for python + ideas wants notes about Python ideas,
        not all Python notes plus all idea notes.
        """
        resp = self.client.get("/api/search?tag=python&tag=ideas", headers=self.editor_headers)
        ids = {m["id"] for m in resp.json()["matches"]}
        self.assertEqual(ids, {self.note_b_id})

    def test_08_tag_filter_no_matches(self):
        """?tag=nonexistent returns empty list."""
        resp = self.client.get("/api/search?tag=nonexistent", headers=self.editor_headers)
        self.assertEqual(resp.json()["matches"], [])

    # ── [SECTION] Date range filtering ────────────────────────────────────

    def test_09_after_filter_excludes_older_notes(self):
        """?after=2026-02-01 returns only notes modified after Feb 1, 2026.

        [WHY MODIFIED FIELD] Using modified (not created) means a note that
        was created long ago but recently updated will still appear in recent
        searches — which matches user expectations.
        """
        resp = self.client.get("/api/search?after=2026-02-01", headers=self.editor_headers)
        ids = {m["id"] for m in resp.json()["matches"]}
        self.assertNotIn(self.note_a_id, ids)  # Jan 15 → excluded
        self.assertIn(self.note_b_id, ids)      # Feb 20 → included

    def test_10_before_filter_excludes_newer_notes(self):
        """?before=2026-02-01 returns only notes modified before Feb 1, 2026."""
        resp = self.client.get("/api/search?before=2026-02-01", headers=self.editor_headers)
        ids = {m["id"] for m in resp.json()["matches"]}
        self.assertIn(self.note_a_id, ids)       # Jan 15 → included
        self.assertNotIn(self.note_b_id, ids)    # Feb 20 → excluded

    def test_11_date_range_combined(self):
        """?after=2026-01-01&before=2026-02-01 is an inclusive date window.

        [WHY LEXICOGRAPHIC COMPARISON] ISO 8601 timestamps sort correctly as
        strings (YYYY-MM-DD...) so >= / <= on raw strings gives exact results
        without needing to parse every timestamp into a datetime object.
        """
        resp = self.client.get(
            "/api/search?after=2026-01-01&before=2026-02-01",
            headers=self.editor_headers,
        )
        ids = {m["id"] for m in resp.json()["matches"]}
        self.assertIn(self.note_a_id, ids)
        self.assertNotIn(self.note_b_id, ids)

    # ── [SECTION] Combined filters ─────────────────────────────────────────

    def test_12_text_and_tag_combined(self):
        """?text=ideas&tag=python returns notes matching both filters.

        [WHY AND SEMANTICS FOR COMBINED FILTERS] All filters are AND-combined.
        A note must satisfy every filter to appear in results.
        """
        resp = self.client.get("/api/search?text=ideas&tag=python", headers=self.editor_headers)
        ids = {m["id"] for m in resp.json()["matches"]}
        self.assertIn(self.note_b_id, ids)
        self.assertNotIn(self.note_c_id, ids)

    def test_13_no_filters_returns_all_notes(self):
        """GET /api/search with no params returns all notes for the user.

        [WHY] When no filters are given, the endpoint acts as a list-all that
        returns the same summary shape as a filtered search, so clients can
        use one code path for both "list" and "search" UI states.
        """
        resp = self.client.get("/api/search", headers=self.editor_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.json()["count"], 4)

    # ── [SECTION] Access control ───────────────────────────────────────────

    def test_14_viewer_role_can_search(self):
        """VIEWER role can access the search endpoint (it's a read operation).

        [WHY VIEWER ACCESS] The old endpoint required EDITOR. Search is a
        read operation — restricting it to EDITOR was overly strict and would
        prevent read-only users (e.g. dashboards, reporting tools) from
        finding their own notes.
        [SECURITY] VIEWER can only see their own notes; the UserScopedNoteRepository
        wrapper enforces that regardless of role.
        """
        resp = self.client.get("/api/search?text=python", headers=self.viewer_headers)
        self.assertEqual(resp.status_code, 200)

    def test_15_unauthenticated_search_is_rejected(self):
        """Search without a token returns 401 Unauthorized.

        [SECURITY] The search endpoint must never be accessible without a
        valid token — leaking even note titles to unauthenticated callers
        would be a data exposure vulnerability.
        """
        resp = self.client.get("/api/search?text=python")
        self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()

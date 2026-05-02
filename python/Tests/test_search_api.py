#!/usr/bin/env python3
"""
Integration tests for the advanced search endpoint: GET /api/search.

Why: The basic search only returned IDs and required EDITOR role. This suite
verifies the extended behaviour: rich result objects, tag filtering, date
range filtering, and VIEWER-accessible access.

TDD: these tests were written before the implementation to define the contract
the endpoint must satisfy.
"""

import sys
import unittest
from pathlib import Path

PROJECT_PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_PYTHON_DIR))

from fastapi.testclient import TestClient
from auth import Role, InMemoryUserRepository
from notes_api import app, get_user_repo, get_repo
from note_repository import MemoryNoteRepository


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def get_test_user_repo():
    repo = InMemoryUserRepository()
    repo.create("viewer", "viewer-password", role=Role.VIEWER)
    repo.create("editor", "editor-password", role=Role.EDITOR)
    return repo


_shared_note_repo = MemoryNoteRepository()


def get_test_note_repo():
    return _shared_note_repo


class TestSearchAPI(unittest.TestCase):
    """Verify GET /api/search with all supported filters."""

    @classmethod
    def setUpClass(cls):
        # Set our own dependency overrides for this test class.
        # Scoping here (not at module level) prevents clobbering other
        # test modules that set their own overrides.
        app.dependency_overrides[get_user_repo] = get_test_user_repo
        app.dependency_overrides[get_repo] = get_test_note_repo

        # Start each run with a clean slate so tests don't bleed into each other.
        _shared_note_repo.clear()
        cls.client = TestClient(app)

        # Log in as editor (needed to create notes) and viewer (to test search access).
        editor_resp = cls.client.post(
            "/auth/login", json={"username": "editor", "password": "editor-password"}
        )
        viewer_resp = cls.client.post(
            "/auth/login", json={"username": "viewer", "password": "viewer-password"}
        )
        cls.editor_headers = {"Authorization": f"Bearer {editor_resp.json()['access_token']}"}
        cls.viewer_headers = {"Authorization": f"Bearer {viewer_resp.json()['access_token']}"}

        # Seed notes for all search tests.
        # Note A: python tag, older modified date injected manually after creation.
        resp_a = cls.client.post(
            "/api/notes",
            json={"title": "Python Basics", "content": "Variables and loops in Python."},
            headers=cls.editor_headers,
        )
        cls.note_a_id = resp_a.json()["id"]

        # Note B: python + ideas tags
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

        # Note C: unrelated content + ideas tag
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

        # Note D: no tags, unique keyword "refactoring"
        resp_d = cls.client.post(
            "/api/notes",
            json={"title": "Code Quality", "content": "Notes on refactoring legacy code."},
            headers=cls.editor_headers,
        )
        cls.note_d_id = resp_d.json()["id"]

        # Manually set older modified timestamps on notes A and B so date
        # range tests have predictable boundaries.
        for note_id, ts in [
            (cls.note_a_id, "2026-01-15T10:00:00"),
            (cls.note_b_id, "2026-02-20T10:00:00"),
        ]:
            note = _shared_note_repo.get(note_id)
            note.modified = ts
            note.created = ts

    # ------------------------------------------------------------------
    # Response shape
    # ------------------------------------------------------------------

    def test_01_response_has_expected_keys(self):
        """Search response includes query, filters, count, and matches keys."""
        resp = self.client.get("/api/search?text=python", headers=self.editor_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("query", data)
        self.assertIn("filters", data)
        self.assertIn("count", data)
        self.assertIn("matches", data)

    def test_02_match_objects_have_summary_fields(self):
        """Each match includes id, title, tags, created, modified, and preview."""
        resp = self.client.get("/api/search?text=python", headers=self.editor_headers)
        matches = resp.json()["matches"]
        self.assertGreater(len(matches), 0)
        for m in matches:
            for key in ("id", "title", "tags", "created", "modified", "preview"):
                self.assertIn(key, m, f"match missing key: {key}")

    # ------------------------------------------------------------------
    # Text search
    # ------------------------------------------------------------------

    def test_03_text_search_returns_matching_notes(self):
        """?text=python returns notes whose title or content contains 'python'."""
        resp = self.client.get("/api/search?text=python", headers=self.editor_headers)
        ids = {m["id"] for m in resp.json()["matches"]}
        self.assertIn(self.note_a_id, ids)  # title contains "Python"
        self.assertIn(self.note_b_id, ids)  # title + content contain "Python"
        self.assertNotIn(self.note_c_id, ids)
        self.assertNotIn(self.note_d_id, ids)

    def test_04_text_search_is_case_insensitive(self):
        """?text=PYTHON matches the same notes as ?text=python."""
        lower = {m["id"] for m in self.client.get("/api/search?text=python", headers=self.editor_headers).json()["matches"]}
        upper = {m["id"] for m in self.client.get("/api/search?text=PYTHON", headers=self.editor_headers).json()["matches"]}
        self.assertEqual(lower, upper)

    def test_05_text_search_no_matches_returns_empty_list(self):
        """?text=xyzzy returns an empty matches list (not a 404 or error)."""
        resp = self.client.get("/api/search?text=xyzzy", headers=self.editor_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["matches"], [])
        self.assertEqual(resp.json()["count"], 0)

    # ------------------------------------------------------------------
    # Tag filtering
    # ------------------------------------------------------------------

    def test_06_single_tag_filter(self):
        """?tag=ideas returns all notes that have the 'ideas' tag."""
        resp = self.client.get("/api/search?tag=ideas", headers=self.editor_headers)
        ids = {m["id"] for m in resp.json()["matches"]}
        self.assertIn(self.note_b_id, ids)
        self.assertIn(self.note_c_id, ids)
        self.assertNotIn(self.note_a_id, ids)
        self.assertNotIn(self.note_d_id, ids)

    def test_07_multiple_tag_filter_is_intersection(self):
        """?tag=python&tag=ideas returns only notes that have BOTH tags."""
        resp = self.client.get("/api/search?tag=python&tag=ideas", headers=self.editor_headers)
        ids = {m["id"] for m in resp.json()["matches"]}
        # Only note B has both python and ideas tags.
        self.assertEqual(ids, {self.note_b_id})

    def test_08_tag_filter_no_matches(self):
        """?tag=nonexistent returns empty list."""
        resp = self.client.get("/api/search?tag=nonexistent", headers=self.editor_headers)
        self.assertEqual(resp.json()["matches"], [])

    # ------------------------------------------------------------------
    # Date range filtering (based on modified field)
    # ------------------------------------------------------------------

    def test_09_after_filter_excludes_older_notes(self):
        """?after=2026-02-01 returns only notes modified after Feb 1, 2026."""
        resp = self.client.get("/api/search?after=2026-02-01", headers=self.editor_headers)
        ids = {m["id"] for m in resp.json()["matches"]}
        # Note A modified Jan 15 → excluded; Note B modified Feb 20 → included.
        self.assertNotIn(self.note_a_id, ids)
        self.assertIn(self.note_b_id, ids)

    def test_10_before_filter_excludes_newer_notes(self):
        """?before=2026-02-01 returns only notes modified before Feb 1, 2026."""
        resp = self.client.get("/api/search?before=2026-02-01", headers=self.editor_headers)
        ids = {m["id"] for m in resp.json()["matches"]}
        # Note A modified Jan 15 → included; Note B modified Feb 20 → excluded.
        self.assertIn(self.note_a_id, ids)
        self.assertNotIn(self.note_b_id, ids)

    def test_11_date_range_combined(self):
        """?after=2026-01-01&before=2026-02-01 is an inclusive date window."""
        resp = self.client.get(
            "/api/search?after=2026-01-01&before=2026-02-01",
            headers=self.editor_headers,
        )
        ids = {m["id"] for m in resp.json()["matches"]}
        # Only Note A falls in [Jan 1 – Feb 1].
        self.assertIn(self.note_a_id, ids)
        self.assertNotIn(self.note_b_id, ids)

    # ------------------------------------------------------------------
    # Combined filters
    # ------------------------------------------------------------------

    def test_12_text_and_tag_combined(self):
        """?text=ideas&tag=python returns notes matching both filters."""
        resp = self.client.get("/api/search?text=ideas&tag=python", headers=self.editor_headers)
        ids = {m["id"] for m in resp.json()["matches"]}
        # Note B: has 'ideas' in title AND 'python' tag.
        self.assertIn(self.note_b_id, ids)
        # Note C: has 'ideas' in title but NOT 'python' tag → excluded.
        self.assertNotIn(self.note_c_id, ids)

    def test_13_no_filters_returns_all_notes(self):
        """GET /api/search with no params returns all notes for the user."""
        resp = self.client.get("/api/search", headers=self.editor_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.json()["count"], 4)

    # ------------------------------------------------------------------
    # Access control
    # ------------------------------------------------------------------

    def test_14_viewer_role_can_search(self):
        """VIEWER role can access the search endpoint (it's a read operation)."""
        resp = self.client.get("/api/search?text=python", headers=self.viewer_headers)
        self.assertEqual(resp.status_code, 200)

    def test_15_unauthenticated_search_is_rejected(self):
        """Search without a token returns 401 Unauthorized."""
        resp = self.client.get("/api/search?text=python")
        self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""
Tests against the real sample notes directory — annotated reference copy.

[ANATOMY]
Unlike most unit tests, this file intentionally points at `test-notes/`.
That makes it a lightweight integration check for the parser, list flow,
and search flow using realistic markdown files instead of synthetic fixtures.
"""

import sys
import unittest
from pathlib import Path

PROJECT_PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_PYTHON_DIR))

import notes0

# [FIXTURE] Shared folder containing example markdown notes shipped with the repo.
SAMPLE_NOTES_DIR = Path(__file__).resolve().parents[2] / "test-notes"


class TestSampleNotes(unittest.TestCase):
    """[CLASS] Real-file smoke tests for the beginner CLI parser flows."""

    def setUp(self):
        self.original_notes_dir = notes0.NOTES_DIR
        notes0.NOTES_DIR = SAMPLE_NOTES_DIR
        self.original_note_extension = notes0.NOTE_EXTENSION
        notes0.NOTE_EXTENSION = ".md"

    def tearDown(self):
        notes0.NOTES_DIR = self.original_notes_dir
        notes0.NOTE_EXTENSION = self.original_note_extension

    def test_read_sample_note_1(self):
        """[VERIFY] read_note() can open a real shipped markdown note."""
        body = notes0.read_note("sample-note-1")
        self.assertIn("Milk", body)

    def test_list_notes_finds_sample_notes(self):
        """[VERIFY] list_notes() parses real metadata from sample files."""
        items = notes0.list_notes()
        titles = [item["title"] for item in items]
        self.assertIn("Grocery List", titles)

    def test_search_finds_matching_note(self):
        """[VERIFY] search_notes() works on realistic content."""
        results = notes0.search_notes("Milk")
        self.assertTrue(len(results) > 0)
        self.assertIn("sample-note-1", results)

    def test_read_sample_note_2(self):
        """[VERIFY] second real file also reads cleanly."""
        body = notes0.read_note("sample-note-2")
        self.assertIsInstance(body, str)
        self.assertIsNotNone(body)


if __name__ == "__main__":
    unittest.main()

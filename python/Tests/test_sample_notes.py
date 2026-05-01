import sys
import unittest
from pathlib import Path

PROJECT_PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_PYTHON_DIR))

import notes0

# Point at the real sample notes folder for all tests in this file
SAMPLE_NOTES_DIR = Path(__file__).resolve().parents[2] / "test-notes"


class TestSampleNotes(unittest.TestCase):
    def setUp(self):
        self.original_notes_dir = notes0.NOTES_DIR
        notes0.NOTES_DIR = SAMPLE_NOTES_DIR
        self.original_note_extension = notes0.NOTE_EXTENSION
        notes0.NOTE_EXTENSION = ".md"

    def tearDown(self):
        notes0.NOTES_DIR = self.original_notes_dir
        notes0.NOTE_EXTENSION = self.original_note_extension

    def test_read_sample_note_1(self):
        note_id = "sample-note-1"
        body = notes0.read_note(note_id)
        self.assertIn("Milk", body)

    def test_list_notes_finds_sample_notes(self):
        items = notes0.list_notes()
        titles = [item["title"] for item in items]
        self.assertIn("Grocery List", titles)

    def test_search_finds_matching_note(self):
        results = notes0.search_notes("Milk")
        self.assertTrue(len(results) > 0)
        self.assertIn("sample-note-1", results)

    def test_read_sample_note_2(self):
        note_id = "sample-note-2"
        body = notes0.read_note(note_id)
        self.assertIsNotNone(body)
        self.assertIsInstance(body, str)


if __name__ == "__main__":
    unittest.main()

import io
import re
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock
from contextlib import redirect_stdout
from pathlib import Path

PROJECT_PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_PYTHON_DIR) not in sys.path:
	sys.path.insert(0, str(PROJECT_PYTHON_DIR))

import notes0


class TestNotes0Basics(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.test_dir = Path(self.tmp.name) / "notes"
		self.original_notes_dir = notes0.NOTES_DIR
		notes0.NOTES_DIR = self.test_dir

	def tearDown(self):
		notes0.NOTES_DIR = self.original_notes_dir
		self.tmp.cleanup()

	def test_setup_returns_notes_dir(self):
		self.assertEqual(notes0.setup(), self.test_dir)

	def test_init_notes_creates_directory(self):
		notes0.init_notes(self.test_dir)
		self.assertTrue(self.test_dir.exists())
		self.assertTrue(self.test_dir.is_dir())

	def test_ensure_notes_dir_creates_directory(self):
		result = notes0.ensure_notes_dir(self.test_dir)
		self.assertEqual(result, self.test_dir)
		self.assertTrue(self.test_dir.exists())
		self.assertTrue(self.test_dir.is_dir())
		self.assertEqual(self.test_dir.stat().st_mode & 0o777, 0o700)

	def test_ensure_notes_dir_is_idempotent(self):
		notes0.ensure_notes_dir(self.test_dir)
		notes0.ensure_notes_dir(self.test_dir)
		self.assertTrue(self.test_dir.exists())
		self.assertTrue(self.test_dir.is_dir())
		self.assertEqual(self.test_dir.stat().st_mode & 0o777, 0o700)

	def test_ensure_notes_dir_friendly_error(self):
		with mock.patch.object(Path, "mkdir", side_effect=PermissionError("denied")):
			with self.assertRaises(RuntimeError) as ctx:
				notes0.ensure_notes_dir(self.test_dir)
		self.assertIn("Could not prepare notes directory", str(ctx.exception))

	def test_slugify_basic(self):
		self.assertEqual(notes0._slugify("My First Note"), "my-first-note")

	def test_create_note_creates_note_file(self):
		notes0.create_note(self.test_dir, "Title", "Body")
		files = list(self.test_dir.glob("*.note"))
		self.assertEqual(len(files), 1)
		text = files[0].read_text(encoding="utf-8")
		self.assertRegex(files[0].stem, r"^note_\d{8}_\d{6}_[a-z0-9-]+(?:-\d+)?$")
		self.assertIn("id: note_", text)
		self.assertIn("title: Title", text)
		self.assertIn("author:", text)
		self.assertIn("Body", text)
		self.assertIn("modified:", text)
		self.assertIn("tags: []", text)
		self.assertIn("status: draft", text)
		self.assertIn("priority: 3", text)

	def test_list_notes_returns_created_note(self):
		notes0.create_note(self.test_dir, "List Me", "hello")
		items = notes0.list_notes()
		self.assertEqual(len(items), 1)
		self.assertEqual(items[0]["title"], "List Me")
		self.assertRegex(items[0]["id"], r"^note_\d{8}_\d{6}_[a-z0-9-]+(?:-\d+)?$")

	def test_atomic_write_creates_file(self):
		notes0.ensure_notes_dir(self.test_dir)
		target = self.test_dir / "atomic.note"
		notes0._atomic_write_text(target, "hello")
		self.assertTrue(target.exists())
		self.assertEqual(target.read_text(encoding="utf-8"), "hello")

	def test_atomic_write_overwrites_existing_file(self):
		notes0.ensure_notes_dir(self.test_dir)
		target = self.test_dir / "atomic.note"
		notes0._atomic_write_text(target, "one")
		notes0._atomic_write_text(target, "two")
		self.assertEqual(target.read_text(encoding="utf-8"), "two")

	def test_atomic_write_leaves_no_temp_files(self):
		notes0.ensure_notes_dir(self.test_dir)
		target = self.test_dir / "atomic.note"
		notes0._atomic_write_text(target, "clean")
		tmp_files = list(self.test_dir.glob(".tmp-note-*"))
		self.assertEqual(tmp_files, [])

	def test_note_validate_requires_title_and_author(self):
		note = notes0.Note(
			id="note_20260430_120000_demo",
			title="",
			author="",
			created="2026-04-30T12:00:00",
			modified="2026-04-30T12:00:00",
		)
		with self.assertRaises(ValueError):
			note.validate()

	def test_note_validate_priority_range(self):
		note = notes0.Note(
			id="note_20260430_120000_demo",
			title="Demo",
			author="Student",
			created="2026-04-30T12:00:00",
			modified="2026-04-30T12:00:00",
			priority=6,
		)
		with self.assertRaises(ValueError):
			note.validate()

	def test_generate_note_id_adds_collision_suffixes(self):
		timestamp = datetime(2026, 4, 30, 12, 0, 0)
		base_id = "note_20260430_120000_my-note"
		notes0.ensure_notes_dir(self.test_dir)
		(self.test_dir / f"{base_id}.note").write_text("", encoding="utf-8")
		(self.test_dir / f"{base_id}-2.note").write_text("", encoding="utf-8")

		note_id = notes0._generate_note_id(self.test_dir, timestamp, "My Note")
		self.assertEqual(note_id, f"{base_id}-3")

	def test_generate_note_id_is_sortable(self):
		first = notes0._generate_note_id(self.test_dir, datetime(2026, 4, 30, 10, 0, 0), "alpha")
		second = notes0._generate_note_id(self.test_dir, datetime(2026, 4, 30, 11, 0, 0), "beta")
		self.assertLess(first, second)

	def test_parse_and_serialize_note_round_trip(self):
		note_text = (
			"---\n"
			"id: note_20260430_120000_demo\n"
			"title: Demo Note\n"
			"author: Student\n"
			"created: 2026-04-30T12:00:00\n"
			"modified: 2026-04-30T12:00:00\n"
			"tags: [demo, yaml]\n"
			"status: draft\n"
			"priority: 3\n"
			"customField: keep-me\n"
			"---\n\n"
			"Hello body\n"
		)
		note = notes0.parse_note(note_text)
		serialized = notes0.serialize_note(note)
		reparsed = notes0.parse_note(serialized)
		self.assertEqual(reparsed.title, "Demo Note")
		self.assertEqual(reparsed.author, "Student")
		self.assertEqual(reparsed.tags, ["demo", "yaml"])
		self.assertEqual(reparsed.extra_metadata.get("customField"), "keep-me")
		self.assertEqual(reparsed.content, "Hello body")

	def test_parse_note_malformed_yaml_reports_line_number(self):
		bad_text = (
			"---\n"
			"title: Demo\n"
			"author Student\n"
			"---\n\n"
			"Body\n"
		)
		with self.assertRaises(ValueError) as ctx:
			notes0.parse_note(bad_text)
		self.assertIn("line", str(ctx.exception).lower())
		self.assertIn("Invalid YAML frontmatter", str(ctx.exception))

	def test_list_notes_skips_bad_files(self):
		notes0.ensure_notes_dir(self.test_dir)
		good_note = (
			"---\n"
			"id: note_20260430_120000_good\n"
			"title: Good\n"
			"author: Student\n"
			"created: 2026-04-30T12:00:00\n"
			"modified: 2026-04-30T12:00:00\n"
			"tags: []\n"
			"status: draft\n"
			"priority: 3\n"
			"---\n\n"
			"Good body\n"
		)
		bad_note = (
			"---\n"
			"title: Bad\n"
			"author Student\n"
			"---\n\n"
			"Bad body\n"
		)
		(self.test_dir / "good.note").write_text(good_note, encoding="utf-8")
		(self.test_dir / "bad.note").write_text(bad_note, encoding="utf-8")

		items = notes0.list_notes()
		self.assertEqual(len(items), 1)
		self.assertEqual(items[0]["title"], "Good")

	def test_list_notes_sorts_by_modified_desc(self):
		notes0.ensure_notes_dir(self.test_dir)
		older = (
			"---\n"
			"id: note_20260430_120000_old\n"
			"title: Old\n"
			"author: Student\n"
			"created: 2026-04-30T10:00:00\n"
			"modified: 2026-04-30T10:00:00\n"
			"tags: []\n"
			"status: draft\n"
			"priority: 3\n"
			"---\n\n"
			"Old body\n"
		)
		newer = (
			"---\n"
			"id: note_20260430_120000_new\n"
			"title: New\n"
			"author: Student\n"
			"created: 2026-04-30T11:00:00\n"
			"modified: 2026-04-30T11:00:00\n"
			"tags: []\n"
			"status: draft\n"
			"priority: 3\n"
			"---\n\n"
			"New body\n"
		)
		(self.test_dir / "old.note").write_text(older, encoding="utf-8")
		(self.test_dir / "new.note").write_text(newer, encoding="utf-8")

		items = notes0.list_notes()
		self.assertEqual(items[0]["title"], "New")
		self.assertEqual(items[1]["title"], "Old")

	def test_read_note_returns_body(self):
		note_id = notes0.create_note(self.test_dir, "Read Me", "Body text")
		body = notes0.read_note(note_id)
		self.assertEqual(body, "Body text")

	def test_read_note_bad_yaml_raises(self):
		notes0.ensure_notes_dir(self.test_dir)
		bad_id = "note_20260430_120000_bad"
		(self.test_dir / f"{bad_id}.note").write_text("---\ntitle: Bad\nauthor Student\n---\n\nbody\n", encoding="utf-8")
		with self.assertRaises(ValueError):
			notes0.read_note(bad_id)

	def test_read_note_missing_raises(self):
		with self.assertRaises(FileNotFoundError):
			notes0.read_note("does-not-exist")

	def test_delete_note_missing_raises(self):
		with self.assertRaises(FileNotFoundError):
			notes0.delete_note("does-not-exist")

	def test_delete_note_removes_existing_file(self):
		note_id = notes0.create_note(self.test_dir, "Delete Me", "Soon gone")
		note_file = self.test_dir / f"{note_id}.note"
		self.assertTrue(note_file.exists())
		notes0.delete_note(note_id)
		self.assertFalse(note_file.exists())

	def test_delete_note_raises_after_prior_delete(self):
		note_id = notes0.create_note(self.test_dir, "Delete Twice", "Gone")
		notes0.delete_note(note_id)
		with self.assertRaises(FileNotFoundError):
			notes0.delete_note(note_id)

	def test_search_notes_empty_query_returns_empty(self):
		self.assertEqual(notes0.search_notes("   "), [])

	def test_help_command_prints_help(self):
		stream = io.StringIO()
		with redirect_stdout(stream):
			notes0.help_command()
		output = stream.getvalue()
		self.assertIn("Future Proof Notes Manager", output)

	def test_update_note_changes_title_and_content(self):
		notes0.create_note(self.test_dir, "Old Title", "Old body")
		note_id = next(self.test_dir.glob("*.note")).stem
		notes0.update_note(note_id, "New Title", "New body")
		body = notes0.read_note(note_id)
		self.assertIn("New body", body)
		after_text = (self.test_dir / f"{note_id}.note").read_text(encoding="utf-8")
		self.assertIn("title: New Title", after_text)
		self.assertIsNotNone(re.search(r"^modified: .+", after_text, re.MULTILINE))

	def test_main_supports_list_command(self):
		# C5: `notes0.py list` must exit 0 — this was the xfail stub.
		# Now that list is wired in main() it should pass cleanly.
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "list"]
			with self.assertRaises(SystemExit) as ctx:
				notes0.main()
			self.assertEqual(ctx.exception.code, 0)
		finally:
			notes0.sys.argv = old_argv

	def test_print_notes_list_empty_shows_hint(self):
		# C5: empty state should guide the user to create their first note.
		stream = io.StringIO()
		with redirect_stdout(stream):
			notes0.print_notes_list([])
		output = stream.getvalue()
		self.assertIn("No notes yet", output)
		self.assertIn("create", output)

	def test_print_notes_list_formats_id_title_date_tags(self):
		# C5: output must include id, date, title, and tags on each row.
		notes_data = [{
			"id": "note_20260430_120000_demo",
			"title": "Demo Note",
			"created": "2026-04-30T12:00:00",
			"modified": "2026-04-30T12:00:00",
			"tags": ["python", "learning"],
			"preview": "Body text",
		}]
		stream = io.StringIO()
		with redirect_stdout(stream):
			notes0.print_notes_list(notes_data)
		output = stream.getvalue()
		self.assertIn("note_20260430_120000_demo", output)
		self.assertIn("Demo Note", output)
		self.assertIn("2026-04-30", output)
		self.assertIn("python", output)
		self.assertIn("learning", output)

	def test_print_notes_list_shows_empty_tags(self):
		# C5: notes without tags should not crash and should print cleanly.
		notes_data = [{
			"id": "note_20260430_130000_no-tags",
			"title": "No Tags Note",
			"created": "2026-04-30T13:00:00",
			"modified": "2026-04-30T13:00:00",
			"tags": [],
			"preview": "",
		}]
		stream = io.StringIO()
		with redirect_stdout(stream):
			notes0.print_notes_list(notes_data)
		output = stream.getvalue()
		self.assertIn("No Tags Note", output)


if __name__ == "__main__":
	unittest.main()


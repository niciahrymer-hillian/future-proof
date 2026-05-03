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


# --- C6: create vertical slice ---

class TestC6CreateVerticalSlice(unittest.TestCase):
	"""C6: full create slice — tags support, confirmation output, --tags CLI flag."""

	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.test_dir = Path(self.tmp.name) / "notes"
		self.original_notes_dir = notes0.NOTES_DIR
		notes0.NOTES_DIR = self.test_dir

	def tearDown(self):
		notes0.NOTES_DIR = self.original_notes_dir
		self.tmp.cleanup()

	def test_create_note_with_tags_stores_them_in_file(self):
		# C6: tags passed to create_note() should appear in the written YAML frontmatter.
		# Effect: tags are round-trippable — what you create is what you list/read back.
		notes0.create_note(self.test_dir, "Tagged Note", "Body", tags=["python", "learning"])
		files = list(self.test_dir.glob("*.note"))
		text = files[0].read_text(encoding="utf-8")
		self.assertIn("python", text)
		self.assertIn("learning", text)

	def test_create_note_confirmation_output_shows_title_and_id(self):
		# C6: the printed confirmation should tell the user what title and ID were assigned.
		# Effect: replaces the old path-only print — more human-readable and scriptable.
		stream = io.StringIO()
		with redirect_stdout(stream):
			note_id = notes0.create_note(self.test_dir, "My Note", "Some content")
		output = stream.getvalue()
		self.assertIn("My Note", output)    # title visible
		self.assertIn(note_id, output)       # ID visible so user can reference it

	def test_create_cli_with_tags_flag_stores_tags(self):
		# C6: `notes0.py create "Title" "Body" --tags "a,b"` should create a note with those tags.
		# Effect: tags are reachable from the command line without entering interactive mode.
		with mock.patch("sys.argv", ["notes0.py", "create", "CLI Tagged", "Body text", "--tags", "a,b"]):
			with mock.patch("notes0.finish"):   # prevent sys.exit from stopping the test
				stream = io.StringIO()
				with redirect_stdout(stream):
					notes0.main()
		files = list(self.test_dir.glob("*.note"))
		self.assertEqual(len(files), 1)
		text = files[0].read_text(encoding="utf-8")
		self.assertIn("- a", text)
		self.assertIn("- b", text)


# --- C7: editor-based create ---

class TestC7EditorCreate(unittest.TestCase):
	"""C7: open $EDITOR with skeleton, validate, save — or abort cleanly."""

	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.test_dir = Path(self.tmp.name) / "notes"
		self.original_notes_dir = notes0.NOTES_DIR
		notes0.NOTES_DIR = self.test_dir

	def tearDown(self):
		notes0.NOTES_DIR = self.original_notes_dir
		self.tmp.cleanup()

	def _make_fake_editor(self, content_to_write):
		"""Return a mock for subprocess.call that overwrites the temp file with the given content.

		Why: we can't open a real editor in a test. Instead, we simulate the user
		saving a file by replacing the temp file contents before the function reads it back.
		Effect: tests can control exactly what the editor 'produces' and check the outcome.
		"""
		def fake_editor(cmd_args):
			# cmd_args is [editor_name, temp_file_path]; write our fake content there.
			Path(cmd_args[1]).write_text(content_to_write, encoding="utf-8")
			return 0  # exit code 0 = editor closed normally
		return fake_editor

	def test_skeleton_contains_all_required_fields(self):
		# C7: the skeleton must include every required YAML field so the user sees what to fill.
		# Effect: if a field is missing from the skeleton, the user may forget it entirely.
		skeleton = notes0._build_skeleton()
		for field in ("title:", "author:", "created:", "modified:", "tags:", "status:", "priority:"):
			self.assertIn(field, skeleton)

	def test_empty_title_aborts_with_no_file_written(self):
		# C7: if the user leaves title blank (or doesn't change it), no note file is created.
		# Effect: the notes directory stays clean — no partial or empty-titled files.
		skeleton_with_blank_title = (
			"---\ntitle: \nauthor: test\ncreated: 2026-04-30T12:00:00\n"
			"modified: 2026-04-30T12:00:00\ntags: []\nstatus: draft\npriority: 3\n---\n\nBody.\n"
		)
		with mock.patch("subprocess.call", side_effect=self._make_fake_editor(skeleton_with_blank_title)):
			result = notes0.create_note_with_editor(self.test_dir)
		self.assertIsNone(result)  # None signals no note was saved
		self.assertEqual(list(self.test_dir.glob("*.note")), [])  # no file on disk

	def test_falls_back_to_nano_when_editor_unset(self):
		# C7: when $EDITOR is unset and no editor argument is given, the command must be 'nano'.
		# Effect: users without $EDITOR configured still get a working editor, not a crash.
		valid_content = (
			"---\ntitle: Nano Note\nauthor: test\ncreated: 2026-04-30T12:00:00\n"
			"modified: 2026-04-30T12:00:00\ntags: []\nstatus: draft\npriority: 3\n---\n\nBody.\n"
		)
		captured_cmd = {}

		def fake_editor(cmd_args):
			captured_cmd["editor"] = cmd_args[0]  # record which editor was called
			Path(cmd_args[1]).write_text(valid_content, encoding="utf-8")
			return 0

		# Pass editor=None AND clear DEFAULT_EDITOR to simulate unset $EDITOR.
		with mock.patch("notes0.DEFAULT_EDITOR", "nano"):
			with mock.patch("subprocess.call", side_effect=fake_editor):
				notes0.create_note_with_editor(self.test_dir, editor=None)

		self.assertEqual(captured_cmd["editor"], "nano")


# --- C8: read vertical slice ---

class TestC8ReadVerticalSlice(unittest.TestCase):
	"""C8: `read` works from CLI args and prompt fallback with clear errors."""

	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.test_dir = Path(self.tmp.name) / "notes"
		self.original_notes_dir = notes0.NOTES_DIR
		notes0.NOTES_DIR = self.test_dir

	def tearDown(self):
		notes0.NOTES_DIR = self.original_notes_dir
		self.tmp.cleanup()

	def test_main_read_with_arg_prints_body_and_exits_zero(self):
		# C8: `notes0.py read <id>` should print content and exit successfully.
		note_id = notes0.create_note(self.test_dir, "Read Arg", "Read body text")
		stream = io.StringIO()
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "read", note_id]
			with redirect_stdout(stream):
				with self.assertRaises(SystemExit) as ctx:
					notes0.main()
			self.assertEqual(ctx.exception.code, 0)
		finally:
			notes0.sys.argv = old_argv
		self.assertIn("Read body text", stream.getvalue())

	def test_main_read_prompt_fallback_works(self):
		# C8: plain `notes0.py read` should prompt for ID and still work.
		note_id = notes0.create_note(self.test_dir, "Read Prompt", "Prompt body")
		stream = io.StringIO()
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "read"]
			with mock.patch("builtins.input", return_value=note_id):
				with redirect_stdout(stream):
					with self.assertRaises(SystemExit) as ctx:
						notes0.main()
			self.assertEqual(ctx.exception.code, 0)
		finally:
			notes0.sys.argv = old_argv
		self.assertIn("Prompt body", stream.getvalue())

	def test_main_read_missing_id_exits_one(self):
		# C8: empty ID should fail fast with exit code 1.
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "read"]
			with mock.patch("builtins.input", return_value="   "):
				with self.assertRaises(SystemExit) as ctx:
					notes0.main()
			self.assertEqual(ctx.exception.code, 1)
		finally:
			notes0.sys.argv = old_argv


# --- C9: delete vertical slice ---

class TestC9DeleteVerticalSlice(unittest.TestCase):
	"""C9: `delete` works from CLI args and prompt fallback with clear errors."""

	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.test_dir = Path(self.tmp.name) / "notes"
		self.original_notes_dir = notes0.NOTES_DIR
		notes0.NOTES_DIR = self.test_dir

	def tearDown(self):
		notes0.NOTES_DIR = self.original_notes_dir
		self.tmp.cleanup()

	def test_main_delete_with_arg_removes_file_and_exits_zero(self):
		# C9: `notes0.py delete <id> --yes` should remove note and exit successfully.
		# --yes is required to bypass the confirmation prompt in non-interactive test runs.
		note_id = notes0.create_note(self.test_dir, "Delete Arg", "Delete body")
		note_file = self.test_dir / f"{note_id}.note"
		self.assertTrue(note_file.exists())
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "delete", note_id, "--yes"]
			with self.assertRaises(SystemExit) as ctx:
				notes0.main()
			self.assertEqual(ctx.exception.code, 0)
		finally:
			notes0.sys.argv = old_argv
		self.assertFalse(note_file.exists())

	def test_main_delete_prompt_fallback_works(self):
		# C9: plain `notes0.py delete` prompts for ID then confirmation.
		# side_effect provides: first the note ID, then 'y' to confirm.
		note_id = notes0.create_note(self.test_dir, "Delete Prompt", "Prompt delete")
		note_file = self.test_dir / f"{note_id}.note"
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "delete"]
			with mock.patch("builtins.input", side_effect=[note_id, "y"]):
				with self.assertRaises(SystemExit) as ctx:
					notes0.main()
			self.assertEqual(ctx.exception.code, 0)
		finally:
			notes0.sys.argv = old_argv
		self.assertFalse(note_file.exists())

	def test_main_delete_missing_id_exits_one(self):
		# C9: empty ID should fail fast with exit code 1.
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "delete"]
			with mock.patch("builtins.input", return_value=""):
				with self.assertRaises(SystemExit) as ctx:
					notes0.main()
			self.assertEqual(ctx.exception.code, 1)
		finally:
			notes0.sys.argv = old_argv


# --- C10: search vertical slice ---

class TestC10SearchVerticalSlice(unittest.TestCase):
	"""C10: `search` works from CLI args and prompt fallback with clear errors."""

	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.test_dir = Path(self.tmp.name) / "notes"
		self.original_notes_dir = notes0.NOTES_DIR
		notes0.NOTES_DIR = self.test_dir

	def tearDown(self):
		notes0.NOTES_DIR = self.original_notes_dir
		self.tmp.cleanup()

	def test_main_search_with_arg_prints_matches_and_exits_zero(self):
		# C10: `notes0.py search <query>` should print matching IDs and exit 0.
		note_id = notes0.create_note(self.test_dir, "Project Plan", "meeting notes and milestones")
		stream = io.StringIO()
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "search", "meeting"]
			with redirect_stdout(stream):
				with self.assertRaises(SystemExit) as ctx:
					notes0.main()
			self.assertEqual(ctx.exception.code, 0)
		finally:
			notes0.sys.argv = old_argv
		output = stream.getvalue()
		self.assertIn("Found:", output)
		self.assertIn(note_id, output)

	def test_main_search_prompt_fallback_works(self):
		# C10: plain `notes0.py search` should prompt for query and return matches.
		note_id = notes0.create_note(self.test_dir, "Alpha", "contains keyword zebra")
		stream = io.StringIO()
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "search"]
			with mock.patch("builtins.input", return_value="zebra"):
				with redirect_stdout(stream):
					with self.assertRaises(SystemExit) as ctx:
						notes0.main()
			self.assertEqual(ctx.exception.code, 0)
		finally:
			notes0.sys.argv = old_argv
		self.assertIn(note_id, stream.getvalue())

	def test_main_search_missing_query_exits_one(self):
		# C10: empty query should fail fast with a clear error and exit code 1.
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "search"]
			with mock.patch("builtins.input", return_value="   "):
				with self.assertRaises(SystemExit) as ctx:
					notes0.main()
			self.assertEqual(ctx.exception.code, 1)
		finally:
			notes0.sys.argv = old_argv


# --- C11: update vertical slice ---

class TestC11UpdateVerticalSlice(unittest.TestCase):
	"""C11: `update` works from CLI args and prompt fallback with clear errors."""

	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.test_dir = Path(self.tmp.name) / "notes"
		self.original_notes_dir = notes0.NOTES_DIR
		notes0.NOTES_DIR = self.test_dir

	def tearDown(self):
		notes0.NOTES_DIR = self.original_notes_dir
		self.tmp.cleanup()

	def test_main_update_with_args_updates_title_and_content(self):
		# C11: `notes0.py update <id> <title> <content>` updates both fields.
		note_id = notes0.create_note(self.test_dir, "Old Title", "Old content")
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "update", note_id, "New Title", "New body text"]
			with self.assertRaises(SystemExit) as ctx:
				notes0.main()
			self.assertEqual(ctx.exception.code, 0)
		finally:
			notes0.sys.argv = old_argv

		text = (self.test_dir / f"{note_id}.note").read_text(encoding="utf-8")
		self.assertIn("title: New Title", text)
		self.assertIn("New body text", text)

	def test_main_update_prompt_fallback_updates_content_only(self):
		# C11: plain `notes0.py update` prompts for fields and supports partial updates.
		note_id = notes0.create_note(self.test_dir, "Keep Title", "Old body")
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "update", note_id]
			with mock.patch("builtins.input", side_effect=["", "Prompt body"]):
				with self.assertRaises(SystemExit) as ctx:
					notes0.main()
			self.assertEqual(ctx.exception.code, 0)
		finally:
			notes0.sys.argv = old_argv

		text = (self.test_dir / f"{note_id}.note").read_text(encoding="utf-8")
		self.assertIn("title: Keep Title", text)
		self.assertIn("Prompt body", text)

	def test_main_update_requires_at_least_one_new_field(self):
		# C11: update should fail when both new title and new content are blank.
		note_id = notes0.create_note(self.test_dir, "No Change", "Body")
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "update", note_id]
			with mock.patch("builtins.input", side_effect=["", "   "]):
				with self.assertRaises(SystemExit) as ctx:
					notes0.main()
			self.assertEqual(ctx.exception.code, 1)
		finally:
			notes0.sys.argv = old_argv


# --- Prefix + editor re-prompt stage ---

class TestPrefixAndEditorUpdateFlow(unittest.TestCase):
	"""ID prefix resolution and editor update behavior checks."""

	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.test_dir = Path(self.tmp.name) / "notes"
		self.original_notes_dir = notes0.NOTES_DIR
		notes0.NOTES_DIR = self.test_dir

	def tearDown(self):
		notes0.NOTES_DIR = self.original_notes_dir
		self.tmp.cleanup()

	def test_unique_prefix_resolves(self):
		# Unique prefix should resolve to one full note ID.
		note_id = notes0.create_note(self.test_dir, "Alpha", "One")
		prefix = note_id[:18]
		resolved = notes0.resolve_note_id_prefix(self.test_dir, prefix)
		self.assertEqual(resolved, note_id)

	def test_ambiguous_prefix_lists_matches(self):
		# Ambiguous prefix must raise with matching IDs listed for user choice.
		notes0.create_note(self.test_dir, "First", "One")
		notes0.create_note(self.test_dir, "Second", "Two")
		# Common prefix for all note IDs: note_YYYYMMDD_ (first 14 chars)
		with self.assertRaises(ValueError) as ctx:
			notes0.resolve_note_id_prefix(self.test_dir, "note_")
		msg = str(ctx.exception)
		self.assertIn("Ambiguous note prefix", msg)
		self.assertIn("Matches:", msg)

	def test_editor_update_bumps_modified_preserves_created_and_reprompts_bad_yaml(self):
		# Simulate two editor saves:
		# 1) invalid YAML -> parser error -> re-prompt
		# 2) valid YAML -> saved successfully
		note_id = notes0.create_note(self.test_dir, "Edit Me", "Original body")
		note_file = self.test_dir / f"{note_id}.note"
		original_note = notes0.parse_note(note_file.read_text(encoding="utf-8"))

		invalid_text = "---\ntitle: bad\nauthor bad\n---\n\nBroken\n"
		valid_text = (
			"---\n"
			f"id: {note_id}\n"
			"title: Edited Title\n"
			f"author: {original_note.author}\n"
			f"created: {original_note.created}\n"
			f"modified: {original_note.modified}\n"
			"tags: []\n"
			"status: draft\n"
			"priority: 3\n"
			"---\n\n"
			"Edited body\n"
		)

		edits = [invalid_text, valid_text]
		call_count = {"n": 0}

		def fake_editor(cmd_args):
			# Each editor open writes next candidate content into temp file.
			Path(cmd_args[1]).write_text(edits[call_count["n"]], encoding="utf-8")
			call_count["n"] += 1
			return 0

		with mock.patch("subprocess.call", side_effect=fake_editor):
			updated_id = notes0.update_note_with_editor(self.test_dir, note_id[:16])

		self.assertEqual(updated_id, note_id)
		self.assertEqual(call_count["n"], 2)  # first invalid, second valid

		saved = notes0.parse_note(note_file.read_text(encoding="utf-8"))
		self.assertEqual(saved.created, original_note.created)  # preserved
		self.assertNotEqual(saved.modified, original_note.modified)  # bumped
		self.assertEqual(saved.title, "Edited Title")
		self.assertEqual(saved.content, "Edited body")


# --- Phase 1 polish: delete confirmation, tag search, stats, --help, near-match ---

class TestPolishAndStats(unittest.TestCase):
	"""Delete confirmation, --tag intersection search, stats command, and CLI polish."""

	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.test_dir = Path(self.tmp.name) / "notes"
		self.original_notes_dir = notes0.NOTES_DIR
		notes0.NOTES_DIR = self.test_dir

	def tearDown(self):
		notes0.NOTES_DIR = self.original_notes_dir
		self.tmp.cleanup()

	def test_delete_confirmation_aborts_on_empty_input(self):
		# Pressing Enter (empty string) at the [y/N] prompt should abort — not delete.
		note_id = notes0.create_note(self.test_dir, "Keep Me", "Body")
		note_file = self.test_dir / f"{note_id}.note"
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "delete", note_id]
			with mock.patch("builtins.input", return_value=""):
				with self.assertRaises(SystemExit) as ctx:
					notes0.main()
			self.assertEqual(ctx.exception.code, 0)  # Aborted cleanly, not an error
		finally:
			notes0.sys.argv = old_argv
		self.assertTrue(note_file.exists())  # File must still be on disk

	def test_delete_yes_flag_skips_confirmation(self):
		# --yes bypasses the confirmation prompt entirely — useful in scripts.
		note_id = notes0.create_note(self.test_dir, "Delete Me", "Body")
		note_file = self.test_dir / f"{note_id}.note"
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "delete", note_id, "--yes"]
			with self.assertRaises(SystemExit) as ctx:
				notes0.main()
			self.assertEqual(ctx.exception.code, 0)
		finally:
			notes0.sys.argv = old_argv
		self.assertFalse(note_file.exists())  # File must be gone

	def test_search_tag_filter_returns_intersection(self):
		# --tag a --tag b should return only notes that have BOTH tags.
		notes0.create_note(self.test_dir, "Both Tags", "Body", tags=["python", "ideas"])
		notes0.create_note(self.test_dir, "One Tag", "Body", tags=["python"])
		notes0.create_note(self.test_dir, "No Tags", "Body")
		matches = notes0.search_notes("", filter_tags=["python", "ideas"])
		self.assertEqual(len(matches), 1)
		note_text = (self.test_dir / f"{matches[0]}.note").read_text(encoding="utf-8")
		self.assertIn("Both Tags", note_text)

	def test_stats_notes_returns_correct_totals(self):
		# stats_notes() should count notes and accumulate tag frequencies.
		notes0.create_note(self.test_dir, "Alpha", "Body", tags=["python", "ideas"])
		notes0.create_note(self.test_dir, "Beta", "Body", tags=["python"])
		stats = notes0.stats_notes()
		self.assertEqual(stats["total"], 2)
		self.assertEqual(stats["unique_tags"], 2)  # python, ideas
		top_tags_dict = dict(stats["top_tags"])
		self.assertEqual(top_tags_dict["python"], 2)  # python appears in both notes
		self.assertIsNotNone(stats["oldest"])
		self.assertIsNotNone(stats["newest"])

	def test_print_stats_json_is_valid_and_complete(self):
		# --json output must be parseable and contain all required keys.
		import json
		notes0.create_note(self.test_dir, "Test Note", "Body", tags=["demo"])
		stats = notes0.stats_notes()
		stream = io.StringIO()
		with redirect_stdout(stream):
			notes0.print_stats(stats, as_json=True)
		parsed = json.loads(stream.getvalue())
		for key in ("total", "unique_tags", "top_tags", "oldest", "newest"):
			self.assertIn(key, parsed)
		self.assertIsInstance(parsed["top_tags"], list)

	def test_main_stats_command_exits_zero(self):
		# `notes0.py stats` should print collection summary and exit 0.
		notes0.create_note(self.test_dir, "A Note", "Body")
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "stats"]
			with self.assertRaises(SystemExit) as ctx:
				notes0.main()
			self.assertEqual(ctx.exception.code, 0)
		finally:
			notes0.sys.argv = old_argv

	def test_main_help_flag_shows_help_and_exits_zero(self):
		# `notes0.py --help` must show help text and exit 0.
		stream = io.StringIO()
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "--help"]
			with redirect_stdout(stream):
				with self.assertRaises(SystemExit) as ctx:
					notes0.main()
			self.assertEqual(ctx.exception.code, 0)
		finally:
			notes0.sys.argv = old_argv
		self.assertIn("Future Proof Notes Manager", stream.getvalue())

	def test_unknown_command_suggests_near_match(self):
		# A typo like 'delet' should suggest 'delete' and exit 1.
		stream = io.StringIO()
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "delet"]
			with redirect_stdout(stream):
				with self.assertRaises(SystemExit) as ctx:
					notes0.main()
			self.assertEqual(ctx.exception.code, 1)
		finally:
			notes0.sys.argv = old_argv
		self.assertIn("delete", stream.getvalue().lower())

	def test_debug_flag_stripped_before_dispatch(self):
		# --debug must be stripped from argv so 'list' still resolves as the command.
		notes0.create_note(self.test_dir, "Test", "Body")
		stream = io.StringIO()
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "--debug", "list"]
			with redirect_stdout(stream):
				with self.assertRaises(SystemExit) as ctx:
					notes0.main()
			self.assertEqual(ctx.exception.code, 0)
		finally:
			notes0.sys.argv = old_argv
		self.assertIn("Test", stream.getvalue())


class TestInteractiveMode(unittest.TestCase):
	"""Coverage for interactive_mode() branches."""

	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.test_dir = Path(self.tmp.name) / "notes"
		self.original_notes_dir = notes0.NOTES_DIR
		notes0.NOTES_DIR = self.test_dir

	def tearDown(self):
		notes0.NOTES_DIR = self.original_notes_dir
		self.tmp.cleanup()

	def _run(self, inputs):
		"""Run interactive_mode with a scripted input sequence; return captured stdout."""
		stream = io.StringIO()
		with mock.patch("builtins.input", side_effect=inputs):
			with redirect_stdout(stream):
				notes0.interactive_mode(self.test_dir)
		return stream.getvalue()

	def test_quit_exits_cleanly(self):
		out = self._run(["exit"])
		self.assertIn("Goodbye", out)

	def test_empty_input_skipped_then_quit(self):
		out = self._run(["", "exit"])
		self.assertIn("Goodbye", out)

	def test_eof_exits_without_error(self):
		stream = io.StringIO()
		with mock.patch("builtins.input", side_effect=EOFError):
			with redirect_stdout(stream):
				notes0.interactive_mode(self.test_dir)

	def test_help_command(self):
		out = self._run(["help", "exit"])
		self.assertIn("Welcome To The Handy Dandy Notebook!", out)

	def test_init_command_creates_directory(self):
		self._run(["folder", "exit"])
		self.assertTrue(self.test_dir.exists())

	def test_list_command_empty(self):
		out = self._run(["list", "exit"])
		self.assertIn("No notes yet", out)

	def test_create_command(self):
		out = self._run(["create", "My Title", "My content", "", "exit"])
		self.assertIn("My Title", out)

	def test_create_command_with_tags(self):
		out = self._run(["create", "Tagged Note", "Body text", "python,ideas", "exit"])
		self.assertIn("Tagged Note", out)

	def test_create_command_empty_title_shows_error(self):
		out = self._run(["create", "", "content", "", "exit"])
		self.assertIn("Error", out)

	def test_stats_command(self):
		notes0.create_note(self.test_dir, "A Note", "Body")
		out = self._run(["stats", "exit"])
		self.assertIn("Total notes", out)

	def test_search_command_found(self):
		notes0.create_note(self.test_dir, "Findable", "unique_xyz_content")
		out = self._run(["search", "unique_xyz_content", "exit"])
		self.assertIn("Found", out)

	def test_search_command_no_results(self):
		# No "Found" heading when nothing matches
		out = self._run(["search", "zzz_no_match_zzz", "exit"])
		self.assertNotIn("Found", out)

	def test_read_command_success(self):
		note_id = notes0.create_note(self.test_dir, "Read Me", "Read body")
		out = self._run(["read", note_id, "exit"])
		self.assertIn("Read body", out)

	def test_read_command_empty_id_shows_error(self):
		out = self._run(["read", "", "exit"])
		self.assertIn("Error", out)

	def test_read_command_not_found_shows_error(self):
		out = self._run(["read", "nonexistent_id_xyz", "exit"])
		self.assertIn("Error", out)

	def test_update_command(self):
		note_id = notes0.create_note(self.test_dir, "Old Title", "Body")
		# inputs: command, note_id, use_editor=n, new_title, new_content, quit
		self._run(["update", note_id, "n", "New Title", "", "exit"])
		self.assertEqual("New Title", notes0.list_notes()[0]["title"])

	def test_update_command_empty_id_shows_error(self):
		out = self._run(["update", "", "exit"])
		self.assertIn("Error", out)

	def test_update_command_no_fields_shows_error(self):
		note_id = notes0.create_note(self.test_dir, "Title", "Body")
		out = self._run(["update", note_id, "n", "", "", "exit"])
		self.assertIn("Error", out)

	def test_delete_command_confirmed(self):
		note_id = notes0.create_note(self.test_dir, "To Delete", "Body")
		self._run(["delete", note_id, "y", "exit"])
		self.assertEqual([], notes0.list_notes())

	def test_delete_command_aborted(self):
		note_id = notes0.create_note(self.test_dir, "Keep Me", "Body")
		out = self._run(["delete", note_id, "n", "exit"])
		self.assertIn("Aborted", out)
		self.assertEqual(1, len(notes0.list_notes()))

	def test_delete_command_empty_id_shows_error(self):
		out = self._run(["delete", "", "exit"])
		self.assertIn("Error", out)

	def test_delete_command_not_found_shows_error(self):
		out = self._run(["delete", "no_such_id", "y", "exit"])
		self.assertIn("Error", out)

	def test_unknown_command_shows_hint(self):
		out = self._run(["badcmd", "exit"])
		self.assertIn("Unknown command", out)


class TestParseNoteErrorPaths(unittest.TestCase):
	"""Coverage for parse_note() error branches."""

	def test_empty_string_raises(self):
		with self.assertRaises(ValueError):
			notes0.parse_note("")

	def test_missing_closing_delimiter_raises(self):
		with self.assertRaises(ValueError):
			notes0.parse_note("---\ntitle: Test\n")

	def test_non_dict_yaml_raises(self):
		with self.assertRaises(ValueError):
			notes0.parse_note("---\n- item1\n- item2\n---\n")

	def test_bad_priority_type_raises(self):
		with self.assertRaises(ValueError):
			notes0.parse_note("---\ntitle: T\nauthor: a\npriority: high\n---\n")

	def test_bad_tags_type_raises(self):
		with self.assertRaises(ValueError):
			notes0.parse_note("---\ntitle: T\nauthor: a\ntags: 99\n---\n")

	def test_tags_as_comma_string_parsed(self):
		note = notes0.parse_note("---\ntitle: T\nauthor: a\ntags: python, ideas\n---\nbody\n")
		self.assertEqual(["python", "ideas"], note.tags)


class TestMainExtraBranches(unittest.TestCase):
	"""Coverage for main() branches not yet hit by earlier tests."""

	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.test_dir = Path(self.tmp.name) / "notes"
		self.original_notes_dir = notes0.NOTES_DIR
		notes0.NOTES_DIR = self.test_dir

	def tearDown(self):
		notes0.NOTES_DIR = self.original_notes_dir
		self.tmp.cleanup()

	def _main(self, argv):
		"""Run main() and capture stdout; always expects SystemExit."""
		stream = io.StringIO()
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = argv
			with redirect_stdout(stream):
				with self.assertRaises(SystemExit):
					notes0.main()
		finally:
			notes0.sys.argv = old_argv
		return stream.getvalue()

	def test_main_init_command(self):
		self._main(["notes0.py", "folder"])
		self.assertTrue(self.test_dir.exists())

	def test_main_create_with_two_args(self):
		self._main(["notes0.py", "create", "CLI Title", "CLI body"])
		notes = notes0.list_notes()
		self.assertEqual(1, len(notes))
		self.assertEqual("CLI Title", notes[0]["title"])

	def test_main_create_empty_title_exits_one(self):
		stream = io.StringIO()
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "create", "   ", "body"]
			with redirect_stdout(stream):
				with self.assertRaises(SystemExit) as ctx:
					notes0.main()
			self.assertEqual(1, ctx.exception.code)
		finally:
			notes0.sys.argv = old_argv

	def test_main_read_with_arg(self):
		note_id = notes0.create_note(self.test_dir, "Readable", "read body")
		out = self._main(["notes0.py", "read", note_id])
		self.assertIn("read body", out)

	def test_main_read_not_found_exits_one(self):
		stream = io.StringIO()
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "read", "no_such_note"]
			with redirect_stdout(stream):
				with self.assertRaises(SystemExit) as ctx:
					notes0.main()
			self.assertEqual(1, ctx.exception.code)
		finally:
			notes0.sys.argv = old_argv

	def test_main_update_with_args(self):
		note_id = notes0.create_note(self.test_dir, "Old", "Body")
		self._main(["notes0.py", "update", note_id, "New Title", "New content"])
		self.assertEqual("New Title", notes0.list_notes()[0]["title"])

	def test_main_update_blank_fields_exits_one(self):
		note_id = notes0.create_note(self.test_dir, "Old", "Body")
		stream = io.StringIO()
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "update", note_id, "", ""]
			with redirect_stdout(stream):
				with self.assertRaises(SystemExit) as ctx:
					notes0.main()
			self.assertEqual(1, ctx.exception.code)
		finally:
			notes0.sys.argv = old_argv

	def test_main_delete_abort_keeps_note(self):
		note_id = notes0.create_note(self.test_dir, "Keep", "Body")
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "delete", note_id]
			with mock.patch("builtins.input", return_value="n"):
				with self.assertRaises(SystemExit) as ctx:
					notes0.main()
			self.assertEqual(0, ctx.exception.code)
		finally:
			notes0.sys.argv = old_argv
		self.assertEqual(1, len(notes0.list_notes()))

	def test_main_search_no_results(self):
		out = self._main(["notes0.py", "search", "zzz_nothing_matches"])
		self.assertIn("No matches", out)

	def test_main_help_command_word(self):
		out = self._main(["notes0.py", "help"])
		self.assertIn("Future Proof Notes Manager", out)

	def test_main_unknown_command_no_suggestion(self):
		stream = io.StringIO()
		old_argv = notes0.sys.argv
		try:
			notes0.sys.argv = ["notes0.py", "xyzqwerty"]
			with redirect_stdout(stream):
				with self.assertRaises(SystemExit) as ctx:
					notes0.main()
			self.assertEqual(1, ctx.exception.code)
		finally:
			notes0.sys.argv = old_argv
		self.assertIn("Unknown command", stream.getvalue())


if __name__ == "__main__":
	unittest.main()


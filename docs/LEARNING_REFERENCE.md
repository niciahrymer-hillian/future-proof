# Future-Proof Learning Reference

This file is a running learning log for the project.
It explains what was built, why it was built, and what each change affects.

---

## 1) Project Map: What Works With What

### Core runtime files
- `python/config.py`
  - Shared configuration for CLI + API.
  - Exports notes directory path, file extension, editor, preview length.
  - Effect: changing config impacts both command-line behavior and API behavior.

- `python/notes0.py`
  - Main app logic (source of truth right now).
  - Contains model, validation, parser/serializer, file operations, and interactive menu flow.
  - Effect: most tests and user features depend on this file.

- `python/notes_api.py`
  - FastAPI wrapper around `notes0.py` logic.
  - Calls core functions from `notes0.py` (create/list/read/update/delete/search).
  - Effect: API behavior follows core logic; API adds HTTP status mapping.

### Test files
- `python/Tests/test_notes0.py`
  - Unit tests for core logic.
  - Effects checked: directory setup, note model validation, ID format/collision, CRUD, parser behavior.

- `python/Tests/test_sample_notes.py`
  - Simpler tests against real sample notes in `test-notes/`.
  - Effect: confirms basic operations work with actual files, not only temp test data.

### Supporting/starter files
- `python/notes-shell.py`, `python/notes1.py`
  - Earlier learning versions and scaffolding.
  - Effect: useful as references; not primary source of truth for current feature set.

---

## 2) Card Progress (Roadmap Tracking)

### Phase 0
- F2 (Centralize config): Done
  - `config.py` in place and used by core logic.

### Phase 1
- C1 (Notes directory bootstrap): Done
  - `ensure_notes_dir()` idempotent, mode `0700` behavior, explicit `init` command, tests added.

- C2 (Note model + validation): Done
  - `Note` dataclass added.
  - `validate()` enforces required title/author and priority range 1-5.
  - ID generation is sortable and collision-safe (`-2`, `-3`, ...).

- C3 (YAML parser read/write): Done
  - `parse_note(text)` and `serialize_note(note)` added.
  - Round-trip behavior tested.
  - Malformed YAML gives clear line-based error.
  - Aggregators skip bad files rather than crashing.

- C4 (File I/O — read, write, list, delete): Done
  - Added atomic write helper (`temp file + rename`) and used it in create/update write paths.
  - `list_notes()` now sorts by `modified` descending, with fallback to `created`.
  - Added focused tests so read/write/list/delete each has at least 3 checks.

- C5 (notes list — first vertical slice): Done
  - `print_notes_list(notes)` added as the single display function for note lists.
  - Output format: `<id>  <created-date>  <title>  [tag1, tag2]`; tags column omitted when empty.
  - Empty-state hint printed when no notes exist: guides user to `notes0.py create`.
  - `list_notes()` now returns `tags` in each dict so formatters don't need to re-parse files.
  - `notes0.py list` wired as a first-class CLI argument command in `main()`.
  - Interactive menu `list` branch updated to call `print_notes_list()` for identical output.
  - `test_main_supports_list_command` upgraded from `@expectedFailure` to a real pass.
  - Added 3 focused C5 tests: empty hint, format check (id/date/title/tags), empty-tags safety.
  - Total: 36 tests in `test_notes0.py`, all passing.

### Next card
- C6 (notes create — complete vertical slice)
  - Non-interactive `notes0.py create "title" "body"` already works; may need polish
  - Prompt fallback for missing args, better error messages, stdin support

---

## 3) Why Key Pieces Exist + What They Affect

### `ensure_notes_dir()`
- Why: avoid command failures when folder does not exist.
- Affects:
  - Startup behavior for CLI/API.
  - Tests for setup and init.
  - Permissions expectations (`0700`).

### `Note.validate()`
- Why: enforce data rules in one place (single source of truth).
- Affects:
  - Create/update correctness.
  - Parser acceptance of loaded files.
  - Validation tests and API 400 behavior (indirectly through core logic).

### `parse_note()` + `serialize_note()`
- Why: centralize note format handling and avoid repeated manual string parsing.
- Affects:
  - Create/read/update/list consistency.
  - Error handling quality for malformed metadata.
  - Stability: bad files can be skipped by list/search paths.

### `_atomic_write_text()`
- Why: avoid partial/corrupted files if a write is interrupted.
- Affects:
  - Create/update reliability on disk.
  - Write tests for create, overwrite, and temp-file cleanup.

### `print_notes_list(notes)`
- Why: single display function ensures `notes0.py list` (CLI) and `list` (interactive menu) produce identical output — that consistency is the whole point of a "vertical slice".
- Affects:
  - CLI `list` command formatting.
  - Interactive menu `list` option formatting.
  - Empty-state messaging (shows hint instead of silence).
  - Tests that assert output format and empty hint.

### List sorting by `modified`
- Why: show most recently changed notes first.
- Affects:
  - `list_notes()` return order (newest first).
  - List tests now assert deterministic order.

### Sortable ID + collision suffixes
- Why: easier file browsing + deterministic ordering + no accidental overwrite.
- Affects:
  - Filename readability.
  - Collision tests.
  - Any feature that resolves notes by file stem.

---

## 4) Test Strategy Notes (What Protects What)

### Unit tests in `test_notes0.py`
- Protect model and business logic regressions.
- Fail fast when format/validation rules change unexpectedly.

### Sample tests in `test_sample_notes.py`
- Confirm real-world behavior with actual note files.
- Useful as quick confidence checks and demos.

### Typical regression chain
- Change parser/model -> likely impacts create/read/list/update tests first.
- Change ID format -> likely impacts regex tests and list/read by ID assumptions.
- Change directory setup -> likely impacts setup/init and any command startup path.

---

## 5) How To Continue Updating This File

When implementing each new card, append:
1. What was added
2. Why it was needed
3. What it affects
4. Which tests prove it
5. Any follow-up risk/next step

Keeping this structure makes the project easier to reuse as a template for future builds.

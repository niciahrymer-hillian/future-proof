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
- C6 (notes create — complete vertical slice): Done
  - `create_note()` now accepts an optional `tags` list; tags are stored in YAML frontmatter.
  - Confirmation output shows `Created: "Title" [id]` instead of just a file path.
  - CLI supports `--tags "python,ideas"` flag.
  - Interactive mode prompts for tags (optional, skippable).
  - Added `TestC6CreateVerticalSlice` with 3 tests (tags in file, confirmation output, --tags flag).
  - Total: 38 tests in `test_notes0.py`, all passing.

- C7 (editor-based create): Done
  - `_build_skeleton()` returns a pre-filled template with all required YAML fields.
  - `create_note_with_editor()` opens `$EDITOR` with the skeleton, validates on save, writes or aborts.
  - Empty title aborts cleanly — no file is written to disk.
  - Falls back to `nano` when `$EDITOR` is unset.
  - `notes0.py create --editor` wired as CLI flag.
  - Bug fix in `parse_note`: YAML null values (`field: `) now parse as `""` not `"None"` (used `or ""`  before `str()`).
  - Added `TestC7EditorCreate` with 3 tests (skeleton fields, empty title abort, nano fallback).

### Next cards
- C8 (notes read — view a single note): Done
  - `read` is now a first-class CLI command in `main()`.
  - Supports both forms: `notes0.py read <id>` and prompt fallback (`notes0.py read`).
  - Empty ID now fails fast with clear error text and exit code `1`.
  - Interactive menu now supports `read` and prints note body text.
  - Added `TestC8ReadVerticalSlice` with 3 tests (arg mode, prompt fallback, missing-ID error).

- C9 (notes delete — remove one note): Done
  - `delete` is now a first-class CLI command in `main()`.
  - Supports both forms: `notes0.py delete <id>` and prompt fallback (`notes0.py delete`).
  - Empty ID now fails fast with clear error text and exit code `1`.
  - Interactive menu now supports `delete`.
  - Added `TestC9DeleteVerticalSlice` with 3 tests (arg mode, prompt fallback, missing-ID error).

- Total: 44 tests in `test_notes0.py`, all passing.

### Next cards
- C10 (notes search — CLI vertical slice): Done
  - `search` is now a first-class CLI command in `main()`.
  - Supports both forms: `notes0.py search <query>` and prompt fallback (`notes0.py search`).
  - Empty query fails fast with clear error text and exit code `1`.
  - Prints `Found:` followed by matching note IDs when matches exist.
  - Added `TestC10SearchVerticalSlice` with 3 tests (arg mode, prompt fallback, missing-query error).

- Total: 47 tests in `test_notes0.py`, all passing.

### Next cards
- C11 (notes update — CLI vertical slice): Done
  - `update` is now a first-class CLI command in `main()`.
  - Supports both modes: full args (`notes0.py update <id> "new title" "new content"`) and prompt fallback.
  - Requires at least one new field (title or content); blank/blank now fails fast with exit code `1`.
  - Interactive menu now supports `update` with the same validation rule.
  - Added `TestC11UpdateVerticalSlice` with 3 tests (arg mode, prompt fallback, empty-update guard).

- Total: 50 tests in `test_notes0.py`, all passing.

### Next cards
- C12 (ID prefix edit UX pass): Done
  - Added `resolve_note_id_prefix()` for view/modify flows.
  - Unique prefix resolves to one note; ambiguous prefix lists all matches.
  - `read` and `update` commands now accept full ID or unique prefix.
  - Added `update_note_with_editor()` for full-note editing with `--editor` mode.
  - Editor save loop now re-prompts automatically on bad YAML until valid save.
  - Edit flow preserves `created`, keeps `id`, and guarantees `modified` advances.
  - Added `TestPrefixAndEditorUpdateFlow` with 3 tests covering prefix resolution,
    ambiguity output, modified/created behavior, and bad-YAML re-prompt loop.

- Total: 53 tests in `test_notes0.py`, all passing.

### Next card
- Phase 2 kickoff (API/UX extension planning)

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

### `_build_skeleton()` (C7)
- Why: open a pre-filled template in the editor so users see required fields and fill in blanks rather than composing from memory. Reduces malformed notes.
- Affects:
  - `create_note_with_editor()` — skeleton is what the user edits.
  - C7 tests verify all fields are present in the skeleton.

### `create_note_with_editor()` (C7)
- Why: many power users prefer editing in their terminal editor rather than inline prompts. This is the editor-based create path.
- Affects:
  - CLI `notes0.py create --editor` flag.
  - Validation gate: empty title aborts before any file is written.
  - `$EDITOR` env var integration; falls back to `nano`.

### `parse_note()` null-value fix (C7 bug fix)
- Why: YAML `title: ` (blank value) is loaded as Python `None`. Using `str(None)` produces the string `"None"` — not an empty string — so empty-field checks silently passed.  Using `or ""` before `str()` converts `None` → `""` correctly.
- Affects:
  - Any note file where a YAML field is left blank.
  - Validation of title, author, created, modified in `parse_note()`.

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

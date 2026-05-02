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

## Phase 2 — Storage Abstraction + REST API with Auth

### Phase 2a — NoteRepository pattern (`note_repository.py`)

**What was added:**
- `NoteRepository` — abstract base class (ABC) defining the storage contract: `add`, `get`, `list_all`, `update`, `delete`, `search`.
- `FilesystemNoteRepository` — delegates to Phase 1 helpers in `notes0.py`. Production implementation.
- `MemoryNoteRepository` — dict-backed in-memory store. Used in all API tests to avoid touching disk.
- `UserScopedNoteRepository` — wraps any inner repo and enforces per-user privacy on every operation.
- `MemoryNoteRepository.clear()` — wipes all notes; used to reset state between test classes.

**Why it exists:**
- The API, tests, and future storage backends (SQL, cloud) should not need to know WHERE notes are stored.
- Writing `FilesystemNoteRepository` + `MemoryNoteRepository` that satisfy the same interface teaches the Liskov Substitution Principle: callers can treat both identically.
- `UserScopedNoteRepository` is the privacy layer. Without it, any authenticated user could read all notes globally. The wrapper intercepts every call and checks `note.user == current_user`.

**What it affects:**
- Any code that creates/reads/updates/deletes notes should go through the repository interface, not call `notes0.py` functions directly.
- Tests: `test_note_repository.py` (11 tests), `test_repository_interface_consistency.py` (1 test).

---

### Phase 2b — Authentication (`auth.py`)

**What was added:**
- `User` dataclass: `username`, `hashed_password`, `role`, `created`.
- `Role` constants + `Role.HIERARCHY` dict: `VIEWER=1`, `EDITOR=2`, `ADMIN=3` — higher number = more access.
- `UserRepository` ABC + `InMemoryUserRepository` — manages user accounts.
- `hash_password()` / `verify_password()` — bcrypt hashing (never store plaintext passwords).
- `create_access_token()` / `verify_access_token()` — JWT tokens via `python-jose`. Tokens expire after 30 minutes.
- `TokenData` — decoded token payload passed to endpoints.

**Why it exists:**
- Without auth, any request can read or modify any note.
- bcrypt adds a work factor — even if the hash leaks, brute-forcing it is computationally expensive.
- JWT tokens are stateless: the server doesn't need to store session data. The token itself carries the user identity and role, and the signature proves it hasn't been tampered with.
- Role hierarchy (numeric levels) lets `require_role(Role.EDITOR)` pass for both EDITOR and ADMIN without listing every valid role explicitly.

**What it affects:**
- Every protected API endpoint depends on `require_role()` and `get_current_user()`.
- Tests: `test_auth.py` (38 tests covering hashing, token creation, expiry, role hierarchy, user CRUD).

---

### Phase 2c — REST API (`notes_api.py`)

**What was added:**
- FastAPI app with 7 endpoints:
  - `POST /auth/login` → returns JWT bearer token
  - `GET /api/notes` → list notes for current user
  - `POST /api/notes` → create note (EDITOR+)
  - `GET /api/notes/{id}` → read one note
  - `PUT /api/notes/{id}` → update note (EDITOR+)
  - `DELETE /api/notes/{id}` → delete note (EDITOR+)
  - `GET /api/search` → search/filter notes (VIEWER+)
- `get_current_user()` dependency — extracts and validates JWT from `Authorization: Bearer <token>` header.
- `require_role(role)` dependency factory — returns 403 if user's role is below the required level.
- `get_user_scoped_repo()` dependency — combines auth + repo: returns a `UserScopedNoteRepository` bound to the current user.
- Pydantic models: `LoginRequest`, `TokenResponse`, `NewNote` (title, content, tags), `NoteChanges` (title, content).

**Why Dependency Injection (Depends()):**
- FastAPI resolves dependencies before calling the endpoint function.
- In tests, `app.dependency_overrides[get_repo] = get_test_note_repo` swaps the production filesystem repo for an in-memory one — no code changes needed in the endpoint itself.
- This is the same principle as passing collaborators as arguments (constructor injection) but at the HTTP framework level.

**Why `UserScopedNoteRepository` in every endpoint:**
- The API never trusts the client to say which user they are. It reads the user from the validated JWT, creates a scoped repo, and all operations automatically filter to that user's notes.

**What it affects:**
- `test_notes_api.py` (11 tests): login flow, CRUD via HTTP, privacy enforcement.

---

### Phase 2d — User field on notes (`notes0.py` + `note_repository.py`)

**What was added:**
- `Note.user: str = ""` — new optional field on the Note dataclass; stores the username of the note's owner.
- `parse_note()` — added `"user"` to `known_fields`; reads `user:` from YAML frontmatter.
- `serialize_note()` — writes `user: <username>` to frontmatter only when non-empty (avoids cluttering CLI-created notes).
- `create_note(user="")` — new optional parameter; sets `note.user` so it's written at creation time.
- `NoteRepository.add(user="")` + all implementations — `user` param flows through ABC → `FilesystemNoteRepository` → `MemoryNoteRepository` → `SQLiteNoteRepository` → `create_note()`.
- `UserScopedNoteRepository.add()` simplified: now calls `self._inner.add(..., user=self._username)` directly. The old approach (create note, then `update()`) failed because `update_note()` only rewrites title/content — it never touches the user field.

**Why this matters:**
- Without this, notes created via the API had `note.user = ""`. `UserScopedNoteRepository.list_all()` filters by `note.user == current_user`, so all notes were invisible to their creator.
- The fix required the user to be stamped at creation time in the initial file write. Trying to patch it after with `update()` was a design mistake — update only persists what it's told to persist.

**What it affects:**
- Any path that creates a note via the API now stores ownership durably on disk.
- Tests: existing auth/API tests continued passing after this fix; the user field is now exercised end-to-end.

---

## Phase 3 — SQL Storage (`note_repository_sql.py`)

**What was added:**
- `SQLiteNoteRepository` — a third NoteRepository implementation backed by SQLite.
- Schema: single `notes` table with all Note fields plus `tags` (JSON), `extra_metadata` (JSON), `user`.
- Composite index on `(user, modified DESC)` — the most common query is "notes for user X, newest first"; the index avoids a full table scan.
- `_get_connection()` — creates a connection with `row_factory = sqlite3.Row` so columns are accessible by name (e.g. `row["title"]`) rather than by position.
- `_row_to_note()` / `_note_to_dict()` — deserialize/serialize between SQLite rows and Note objects; handles JSON round-trip for tags and extra_metadata.
- `clear()` method — for test teardown.
- Timestamp collision guard in `add()`: if two notes are created in the same second, `_generate_id()` queries the DB to find an unused ID.
- Kept in a separate file (`note_repository_sql.py`, not merged into `note_repository.py`) so the filesystem and memory implementations are easy to compare side-by-side.

**Why SQLite vs filesystem:**
- Filesystem stores one file per note. Fast for small collections; slow for queries that need to scan all notes (search, listing).
- SQLite stores all notes in one file. A single indexed query can find 10 notes in a million in microseconds.
- SQLite is built into Python (`import sqlite3`) — no extra install needed in production.

**What it affects:**
- `test_note_repository_sql.py` (25 tests): full CRUD, listing/sorting, search, persistence across instances, user field.
- `test_repository_interface_consistency.py` (1 test): runs the same operations on `MemoryNoteRepository` and `SQLiteNoteRepository` and asserts identical results — proves the interface contract holds across backends.

---

## Option B — Advanced Search & Filtering

**What was added:**
- `GET /api/search` extended to support four optional query parameters:
  - `?text=...` — keyword in title or preview (case-insensitive)
  - `?tag=python&tag=ideas` — tag intersection; note must have ALL listed tags (AND logic)
  - `?after=2026-01-01` — notes modified on or after this date
  - `?before=2026-05-01` — notes modified on or before this date
- Filters are all optional and all AND-combined (a note must pass every active filter).
- Response shape changed from `{"query": ..., "matches": ["id1", ...]}` to a richer envelope: `{"query": ..., "filters": {...}, "count": N, "matches": [<summary dicts>]}`. Each match now includes `id`, `title`, `tags`, `created`, `modified`, `preview`.
- Access fixed from `Role.EDITOR` → `Role.VIEWER` — search is a read operation.
- `NewNote` model gained a `tags` field (it was missing — tags sent by clients were silently dropped).
- `create_new_note()` now passes `tags=note_data.tags` to `repo.add()`.

**Why VIEWER for search:**
- An EDITOR-only search gate would block read-only users (dashboards, reporting tools) from finding their own notes. Searching is inherently a read operation.

**Why ISO 8601 string comparison for dates:**
- `"2026-05-01T12:00:00" >= "2026-01-01"` works correctly because ISO 8601 strings sort lexicographically in the same order as the actual dates. No datetime parsing needed for boundary comparisons.

**Why AND semantics for multi-tag filter:**
- `?tag=python&tag=ideas` means "notes about Python ideas", not "all Python notes plus all idea notes". AND is more precise and matches what a user intuitively expects when they add multiple tags.

**Bug fixed:** `NewNote.tags` was missing from the Pydantic model — any tags sent in `POST /api/notes` were silently ignored since Phase 2. Fixed by adding `tags: Optional[List[str]] = None` to `NewNote` and passing it through in `create_new_note()`.

**What it affects:**
- `test_search_api.py` (15 tests, TDD — written before implementation): response shape, text search, case-insensitivity, tag intersection, date ranges, combined filters, VIEWER access, unauthenticated rejection.
- Dependency isolation: overrides are now scoped to `setUpClass` (not module-level) so test files don't clobber each other's `app.dependency_overrides` when the full suite runs together.

---

## Current State

| Layer | File | Tests |
|---|---|---|
| Core CRUD + CLI | `python/notes0.py` | 102 (test_notes0.py) |
| Authentication | `python/auth.py` | 38 (test_auth.py) |
| Repository interface | `python/note_repository.py` | 11 (test_note_repository.py) |
| SQL repository | `python/note_repository_sql.py` | 25 (test_note_repository_sql.py) |
| Interface consistency | — | 1 (test_repository_interface_consistency.py) |
| REST API (CRUD + auth) | `python/notes_api.py` | 11 (test_notes_api.py) |
| Advanced search | `python/notes_api.py` | 15 (test_search_api.py) |
| Frontend (HTML) | `python/notes_api.py` + `python/templates/` | 18 (test_frontend.py) |
| Admin API (user management) | `python/notes_api.py` | 15 (test_admin_api.py) |
| Sample note integration | `test-notes/` | 4 (test_sample_notes.py) |
| **Total** | | **237** |

**Annotated copies in `references/`:**
- `notes0_annotated_cp.py`, `notes_api_annotated_cp.py`, `config_annotated_cp.py`
- `notes-shell_annotated_cp.py`, `note_repository_annotated_cp.py`
- `note_repository_sql_annotated_cp.py`, `test_search_api_annotated_cp.py`, `test_frontend_annotated_cp.py`
- `test_notes_api_annotated_cp.py`, `auth_annotated_cp.py`, `test_admin_api_annotated_cp.py`

---

## Option C — Server-rendered HTML Frontend

**What was added:**
- 9 new HTML route handlers added to `notes_api.py`: `GET/POST /login`, `POST /logout`, `GET /`, `GET/POST /notes/new`, `GET /notes/{id}`, `GET/POST /notes/{id}/edit`, `POST /notes/{id}/delete`, `GET /search`.
- `SessionMiddleware` added to the FastAPI app — stores a signed, encrypted session cookie on the client. Requires `itsdangerous` (installed with Starlette).
- `Jinja2Templates` pointed at `python/templates/` directory.
- Six HTML templates: `base.html` (shared nav/layout), `login.html`, `notes_list.html`, `note_create.html`, `note_detail.html`, `note_edit.html`, `search.html`.
- Dependencies installed: `jinja2`, `python-multipart`, `itsdangerous`.

**Why session cookies instead of JWT for the browser frontend:**
- JWT tokens work well for API clients (mobile apps, scripts) that can manage Authorization headers.
- Browsers don't natively send Authorization headers on page loads. Session cookies are sent automatically with every request.
- Both auth paths coexist: the `/api/...` routes still require `Authorization: Bearer <token>`; the HTML routes use the session cookie.

**Why `_get_scoped_repo` uses `Depends(get_repo)`:**
- A helper that calls `get_repo()` directly bypasses FastAPI's dependency override system — test injections would be silently ignored.
- By declaring `inner: NoteRepository = Depends(get_repo)` as a parameter, FastAPI resolves the override before calling the helper.
- This is the same principle as the API routes: all storage access goes through the DI system so tests can inject a MemoryNoteRepository.

**Why POST for delete:**
- HTML forms only support GET and POST. A `<form method="delete">` is not valid HTML.
- The standard solution is `POST /notes/{id}/delete` (or a hidden `_method` field). We use the explicit path approach.

**Template API version note:**
- Starlette 0.40+ changed `TemplateResponse(name, context)` to `TemplateResponse(request, name, context)` — `request` is now the first positional argument. Passing a context dict as the first arg causes a `TypeError: unhashable type 'dict'` deep in Jinja2's LRU cache. Fixed by updating all calls to the new signature.

**Test isolation fix (extended):**
- `test_notes_api.py` previously set `app.dependency_overrides` at module level. This worked when the file ran first, but `test_frontend.py`'s `tearDownClass` removes overrides via `.pop()`, leaving `test_notes_api` classes without overrides.
- Fix: moved all overrides into `setUpClass`/`tearDownClass` in every class in `test_notes_api.py`. Now every test class is self-contained regardless of run order.

**What it affects:**
- `test_frontend.py` (18 tests, TDD): login/logout, notes list, create/edit/delete forms, search page, auth guards.
- `test_notes_api.py` — `setUpClass`/`tearDownClass` pattern applied to all three test classes.

---

## Option D — Admin API (User Management)

**What was added:**
- 5 new ADMIN-only endpoints in `notes_api.py`:
  - `GET /admin/users` — list all user accounts
  - `POST /admin/users` — create a new user account (409 on duplicate)
  - `GET /admin/users/{username}` — get one user by username (404 if missing)
  - `PUT /admin/users/{username}/role` — change a user's role (400 for unknown roles)
  - `DELETE /admin/users/{username}` — soft-deactivate a user (blocks login, preserves record)
- 3 new Pydantic models in `notes_api.py`: `NewUserRequest`, `UpdateRoleRequest`, `AdminUserResponse`
- `deactivate()` method added to `InMemoryUserRepository` in `auth.py`
  - **Why separate from `delete()`:** `delete()` hard-removes the record; `deactivate()` sets `is_active=False` while keeping the record. This preserves account history and note ownership traceability.

**Why ADMIN-only:** User management has privilege-escalation risk. An EDITOR promoting themselves to ADMIN would break the entire access control model. Restricting to ADMIN means only a current admin can modify accounts.

**Why soft-delete (deactivate) instead of hard-delete:**
- Hard delete removes the record entirely — any notes the user created become orphaned or ambiguous.
- Soft delete (`is_active=False`) blocks login immediately via the existing `authenticate()` check, while leaving the account data intact for audit purposes.

**Bug fixed: test fixture singleton pattern:**
- `TestAdminDeactivateUser` needs deactivation in one request to be visible in the next (login check).
- Using a factory (`_make_user_repo`) creates a fresh repo per-request → mutation is lost.
- Fix: `setUpClass` creates one shared `InMemoryUserRepository` instance and registers `lambda: cls._user_repo` as the override, so all requests share the same in-memory state.
- This is a generalisation of the singleton pattern already used for `_shared_note_repo`.

**What it affects:**
- `notes_api.py` — new endpoints, new request/response models
- `auth.py` — new `deactivate()` method on `InMemoryUserRepository`
- Tests: 15 new tests in `test_admin_api.py`

**Annotated copies added/updated:**
- `auth_annotated_cp.py` — updated with `deactivate()` method annotation
- `notes_api_annotated_cp.py` — updated with admin endpoints section
- `test_admin_api_annotated_cp.py` — new

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

When implementing each new phase or feature, append a new section with:
1. **What was added** — new files, functions, classes, endpoints
2. **Why it was needed** — the problem it solves
3. **What it affects** — which other files/layers depend on it
4. **Which tests prove it** — test file + count
5. **Any bugs fixed along the way**
6. **Any follow-up risk/next step**

Update the **Current State** table after each phase to keep the test count accurate.

Keeping this structure makes the project easier to reuse as a template for future builds.

#!/usr/bin/env python3
"""
Annotated reference for `python/Tests/test_notes0.py`.

[ANATOMY]
This is the largest test file in the project because it tracks the entire
Phase 1 beginner CLI journey. The source test file is intentionally broad:
it protects low-level parsing helpers, file IO safety, command-line vertical
slices, editor flows, stats, search, delete confirmation, interactive mode,
and many edge/error branches.

[WHY THIS FILE IS LARGE]
`notes0.py` is both the core domain model and the beginner-facing CLI.
Instead of one narrow unit-test layer, it needed a staircase of tests that
mirror how the feature set was built card by card.

[MAP OF TEST GROUPS]
- `TestNotes0Basics`: setup, directory prep, slugify, create/list/read/delete,
  atomic writes, parse/serialize round-trip, malformed YAML handling.
- `TestC6CreateVerticalSlice`: create command end-to-end, tags, confirmation output.
- `TestC7EditorCreate`: editor-based create flow, skeleton fields, nano fallback.
- `TestC8ReadVerticalSlice`: read command with CLI arg and prompt fallback.
- `TestC9DeleteVerticalSlice`: delete command, confirmation flow, `--yes` bypass.
- `TestC10SearchVerticalSlice`: search command with CLI arg and prompt fallback.
- `TestC11UpdateVerticalSlice`: update command with args and prompt-driven partial updates.
- `TestPrefixAndEditorUpdateFlow`: prefix resolution, ambiguous prefixes, editor retry loop.
- `TestPolishAndStats`: delete UX polish, tag-intersection search, stats, help, near-match suggestion.
- `TestInteractiveMode`: menu-driven REPL coverage.
- `TestParseNoteErrorPaths`: parser error branches and coercion edge cases.
- `TestMainExtraBranches`: remaining `main()` dispatch branches not already covered.

[WHY THIS ANNOTATED COPY IS A MAP, NOT A LINE-BY-LINE MIRROR]
The source file is roughly 1200 lines and mostly repetitive assertion code.
For reuse as a reference template, the important information is:
1. which user-facing behavior each test class protects,
2. how temporary directories isolate filesystem state,
3. how `sys.argv`, `input()`, `redirect_stdout`, and mocked editors are used,
4. which vertical slices exist so future ports/extensions keep behavior stable.

[COMMON PATTERNS USED THROUGHOUT]
- Temporary directory fixture:
  each class patches `notes0.NOTES_DIR` to a disposable folder.
- CLI simulation:
  tests patch `notes0.sys.argv` and expect `SystemExit` from `main()`.
- Prompt simulation:
  tests patch `builtins.input` with `return_value` or `side_effect`.
- Output capture:
  `redirect_stdout(io.StringIO())` checks user-facing text, not just return values.
- Editor simulation:
  tests patch `subprocess.call` so no real editor opens during CI.

[KEY BEHAVIOR GUARANTEES FROM THE SOURCE TEST FILE]
- Notes directory setup is idempotent and uses `0700` permissions.
- Note IDs are sortable and collision-safe.
- YAML frontmatter parsing is strict enough to reject malformed metadata.
- Atomic writes leave no temp-file residue.
- CRUD commands all work from CLI arguments and prompt fallback.
- Tag creation/search/stats remain consistent across CLI and interactive mode.
- Editor-based create/update flows preserve required metadata and retry on bad YAML.
- Interactive mode handles quit/help/EOF/unknown commands cleanly.
- Helpful UX exists for empty collections, near-miss commands, and abortable deletes.

[HOW TO USE THIS WITH THE SOURCE FILE]
When you need exact assertions or test fixture details, read the source file:
`python/Tests/test_notes0.py`.
Use this annotated copy as the roadmap for why each test block exists and which
user workflow it protects.
"""

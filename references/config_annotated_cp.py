#!/usr/bin/env python3
# ══════════════════════════════════════════════════════════════════════
# [MODULE] config_annotated.py
# Learning reference copy of config.py — production file is config.py
# This file keeps all comments and adds anatomy labels so you can see
# exactly what kind of construct each line is.
#
# ANATOMY GUIDE (labels used throughout this file)
# ──────────────────────────────────────────────────
# [MODULE]    the file itself; Python runs it top-to-bottom on import
# [IMPORT]    pulls stdlib / third-party / local code into this scope
# [CONSTANT]  module-level name that never changes after the file loads
# [VARIABLE]  a name that holds a value (local to a function or module)
# ══════════════════════════════════════════════════════════════════════
"""Configuration for Future Proof Notes CLI.

This module is the single source of truth for all path and runtime
settings. Importing config means every other file (notes0.py, notes_api.py,
tests) reads settings from one place — change a value here and it
propagates everywhere automatically.
"""

# ── [IMPORT] stdlib ────────────────────────────────────────────────────
import os           # os.getenv() reads environment variables at runtime
from pathlib import Path  # Path turns string paths into objects with helper methods

# ── [CONSTANT] NOTES_DIR ───────────────────────────────────────────────
# Where all .note files are stored on disk.
# os.getenv("NOTES_HOME", fallback) checks the environment variable first
# so the user can override the path without editing source code, e.g.:
#   NOTES_HOME=/tmp/test-notes python notes0.py list
# If NOTES_HOME is not set, the default is ~/.notes/notes
# .expanduser() converts the leading ~ into the actual home directory path.
NOTES_DIR = Path(os.getenv("NOTES_HOME", Path.home() / ".notes" / "notes")).expanduser()

# ── [CONSTANT] NOTE_EXTENSION ──────────────────────────────────────────
# The file extension appended to every note filename (e.g. "my-note.note").
# Stored as a constant so if you ever rename the extension you change it
# in one place and every glob pattern, path join, and test updates too.
NOTE_EXTENSION = ".note"

# ── [CONSTANT] DEFAULT_EDITOR ──────────────────────────────────────────
# The editor opened by `notes0.py create --editor` and `update --editor`.
# Respects the user's $EDITOR environment variable (standard Unix convention).
# Falls back to nano — a safe, always-available terminal editor.
DEFAULT_EDITOR = os.getenv("EDITOR", "nano")

# ── [CONSTANT] PREVIEW_CHARS ───────────────────────────────────────────
# Maximum characters shown from a note's body in the `list` view.
# Keeping this small prevents the table from wrapping onto multiple lines.
PREVIEW_CHARS = 120

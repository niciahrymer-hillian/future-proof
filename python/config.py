#!/usr/bin/env python3
"""Configuration for Future Proof Notes CLI."""

import os
from pathlib import Path

# Central config keeps paths/settings in one place for CLI + API.
# Honors NOTES_HOME when provided; otherwise defaults to ~/.notes/notes
NOTES_DIR = Path(os.getenv("NOTES_HOME", Path.home() / ".notes" / "notes")).expanduser()

# File extension used for notes
NOTE_EXTENSION = ".note"

# Honors EDITOR when provided; otherwise defaults to nano
DEFAULT_EDITOR = os.getenv("EDITOR", "nano")

# Max number of characters used for preview text
PREVIEW_CHARS = 120

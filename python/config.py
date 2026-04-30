#!/usr/bin/env python3

import os
from pathlib import Path

NOTES_DIR = Path(os.getenv("NOTES_HOME", Path.home() / ".notes" / "notes")).expanduser()

NOTE_EXTENSION = ".note"

DEFAULT_EDITOR = os.getenv("EDITOR", "nano")

PREVIEW_CHARS = 120

#!/usr/bin/env python3
"""Annotated reference copy of the notes API.

This file mirrors the runtime API behavior and adds concise labels
that explain what each section does and why it exists.
"""

from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from config import NOTES_DIR
from notes0 import (
	create_note,
	delete_note,
	init_notes,
	list_notes,
	read_note,
	search_notes,
	update_note,
)


# [APP] FastAPI application object.
# Effect: exposes OpenAPI docs at /docs and serves all route handlers below.
app = FastAPI(title="Future Proof Notes API", version="0.1.0")


# [MODEL] Request body for creating a note.
# Effect: title/content must be present and non-empty before route logic runs.
class NewNote(BaseModel):
	"""Data needed to create a note."""

	title: str = Field(min_length=1)
	content: str = Field(min_length=1)


# [MODEL] Partial updates for a note.
# Effect: client can send title only, content only, or both.
class NoteChanges(BaseModel):
	"""Data used to update a note."""

	title: Optional[str] = None
	content: Optional[str] = None


@app.on_event("startup")
def startup() -> None:
	"""Create the notes folder if it does not exist."""
	# [WHY] Keeps API safe on a fresh machine with no pre-created directory.
	init_notes(NOTES_DIR)


@app.get("/health")
@app.get("/status")
def status() -> dict:
	"""Quick check that the API is running."""
	return {"status": "running"}


@app.get("/api/notes")
def list_all_notes() -> List[dict]:
	"""Return all notes."""
	# [ROUTE] Thin wrapper around core notes logic.
	return list_notes()


@app.post("/api/notes", status_code=201)
def create_new_note(note_data: NewNote) -> dict:
	"""Create one note and return its id."""
	# [FLOW] API delegates storage format and validation to notes0.create_note.
	note_id = create_note(NOTES_DIR, note_data.title, note_data.content)
	return {"id": note_id}


@app.get("/api/notes/{note_id}")
def get_one_note(note_id: str) -> dict:
	"""Get one note by id."""

	try:
		body = read_note(note_id)
		return {"id": note_id, "content": body}
	except FileNotFoundError:
		# [HTTP MAP] Convert file-layer error into an HTTP 404.
		raise HTTPException(status_code=404, detail="Note was not found")


@app.put("/api/notes/{note_id}")
def update_one_note(note_id: str, changes: NoteChanges) -> dict:
	"""Update one note by id."""

	try:
		# [ADAPTER] Preserve existing update_note signature by passing empty strings
		# when an optional field is omitted in the API payload.
		update_note(note_id, new_title=changes.title or "", new_content=changes.content or "")
		return {"id": note_id, "updated": True}
	except FileNotFoundError:
		raise HTTPException(status_code=404, detail="Note was not found")
	except ValueError as err:
		# [HTTP MAP] Validation/business-rule failures become a 400.
		raise HTTPException(status_code=400, detail=str(err)) from err


@app.delete("/api/notes/{note_id}")
def delete_one_note(note_id: str) -> dict:
	"""Delete one note by id."""

	try:
		delete_note(note_id)
		return {"id": note_id, "deleted": True}
	except FileNotFoundError:
		raise HTTPException(status_code=404, detail="Note was not found")


@app.get("/api/search")
def search_all_notes(text: str = Query(default="")) -> dict:
	"""Search all notes using the text query."""
	# [QUERY] Keep parameter short for convenient URL usage: /api/search?text=foo
	matches = search_notes(text)
	return {"query": text, "matches": matches}

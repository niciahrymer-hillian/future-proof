#!/usr/bin/env python3
"""Very simple API for the notes app."""

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

# FastAPI app object powers the API docs at /docs and request routing.
app = FastAPI(title="Future Proof Notes API", version="0.1.0")


class NewNote(BaseModel):
    """Data needed to create a note."""

    # Pydantic checks these required fields before our route logic runs.
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)


class NoteChanges(BaseModel):
    """Data used to update a note."""

    # Optional fields let clients update title or content independently.
    title: Optional[str] = None
    content: Optional[str] = None


@app.on_event("startup")
def startup() -> None:
    """Create the notes folder if it does not exist."""
    # Startup hook keeps API calls safe even on a fresh machine.
    init_notes(NOTES_DIR)


@app.get("/health")
@app.get("/status")
def status() -> dict:
    """Quick check that the API is running."""
    return {"status": "running"}


@app.get("/api/notes")
def list_all_notes() -> List[dict]:
    """Return all notes."""
    # Thin route: delegate business logic to notes0.py.
    return list_notes()


@app.post("/api/notes", status_code=201)
def create_new_note(note_data: NewNote) -> dict:
    """Create one note and return its id."""
    # NOTES_DIR is shared config, so API + CLI write to same storage.
    note_id = create_note(NOTES_DIR, note_data.title, note_data.content)
    return {"id": note_id}


@app.get("/api/notes/{note_id}")
def get_one_note(note_id: str) -> dict:
    """Get one note by id."""

    try:
        body = read_note(note_id)
        return {"id": note_id, "content": body}
    except FileNotFoundError:
        # Convert Python file errors into HTTP status codes for clients.
        raise HTTPException(status_code=404, detail="Note was not found")


@app.put("/api/notes/{note_id}")
def update_one_note(note_id: str, changes: NoteChanges) -> dict:
    """Update one note by id."""

    try:
        # Empty-string defaults keep update_note signature simple.
        update_note(note_id, new_title=changes.title or "", new_content=changes.content or "")
        return {"id": note_id, "updated": True}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Note was not found")
    except ValueError as err:
        # Validation problems become a 400 (bad request).
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
    # Query parameter name is kept short for easy URL usage.
    matches = search_notes(text)
    return {"query": text, "matches": matches}

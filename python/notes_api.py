#!/usr/bin/env python3
"""REST API for the notes app with authentication and authorization.

WHY DEPENDENCY INJECTION:
  Each endpoint receives an authenticated user and a user-scoped repository.
  The API doesn't need to know WHERE users are stored or HOW notes are protected.
  Tests can override get_repo() and get_user_repo() to inject memory-backed
  implementations.

AUTH FLOW:
  1. Client POSTs credentials to /auth/login
  2. API verifies password and returns a JWT token
  3. Client includes token in Authorization: Bearer <token> header on subsequent requests
  4. API dependency verify_token() decodes and validates the token
  5. If valid, the endpoint receives the TokenData and passes it to user-scoped repository
  6. If invalid, dependency raises 401 Unauthorized without calling the endpoint
"""

from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status, Header
from pydantic import BaseModel, Field

from auth import (
    InMemoryUserRepository,
    Role,
    TokenData,
    User,
    UserRepository,
    create_access_token,
    verify_access_token,
    verify_password,
)
from config import NOTES_DIR
from note_repository import FilesystemNoteRepository, NoteRepository, UserScopedNoteRepository
from notes0 import init_notes

app = FastAPI(title="Future Proof Notes API", version="0.1.0")


# ---------------------------------------------------------------------------
# Dependencies: repositories
# ---------------------------------------------------------------------------

# Global user repository — in production this would be persistent storage
_user_repo: Optional[UserRepository] = None


def get_user_repo() -> UserRepository:
    """Return the active user repository."""
    global _user_repo
    if _user_repo is None:
        _user_repo = InMemoryUserRepository()
    return _user_repo


def get_repo() -> NoteRepository:
    """Return the filesystem-backed repository used in production."""
    return FilesystemNoteRepository(NOTES_DIR)


# ---------------------------------------------------------------------------
# Dependencies: authentication
# ---------------------------------------------------------------------------

async def get_current_user(authorization: str = Header(None)) -> TokenData:
    """Extract and validate JWT token from Authorization header.

    EFFECT: Returns the decoded user info if valid.
            Raises 401 if header is missing, malformed, or token is invalid/expired.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Use: Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1]
    try:
        return verify_access_token(token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_user_scoped_repo(
    current_user: TokenData = Depends(get_current_user),
    inner_repo: NoteRepository = Depends(get_repo),
) -> UserScopedNoteRepository:
    """Return a note repository scoped to the authenticated user.

    EFFECT: All note operations are filtered to only that user's notes.
    """
    scoped = UserScopedNoteRepository(inner_repo)
    scoped.set_user(current_user.username)
    return scoped


def require_role(required_role: str):
    """Create a dependency that enforces a minimum role.

    USAGE: @app.get("/admin/users")
           def list_users(user: TokenData = Depends(require_role(Role.ADMIN))):
    """

    async def check_role(current_user: TokenData = Depends(get_current_user)) -> TokenData:
        # Check if user's role is sufficient by comparing hierarchy levels
        user_level = Role.HIERARCHY.get(current_user.role, -1)
        required_level = Role.HIERARCHY.get(required_role, -1)
        
        if user_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {required_role}, your role: {current_user.role}",
            )
        return current_user

    return check_role


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    """Credentials for authentication."""

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    """JWT token returned on successful login."""

    access_token: str
    token_type: str = "bearer"
    username: str
    role: str


class UserResponse(BaseModel):
    """User info returned by endpoints."""

    username: str
    role: str
    created: str


class NewNote(BaseModel):
    """Data needed to create a note."""

    title: str = Field(min_length=1)
    content: str = Field(min_length=1)


class NoteChanges(BaseModel):
    """Data used to update a note."""

    title: Optional[str] = None
    content: Optional[str] = None


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@app.on_event("startup")
def startup() -> None:
    """Create the notes folder if it does not exist."""
    init_notes(NOTES_DIR)
    # Create a default admin user for testing (remove in production).
    try:
        repo = get_user_repo()
        repo.create("admin", "admin-password", role=Role.ADMIN)
    except ValueError:
        pass  # User already exists


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.post("/auth/login", response_model=TokenResponse)
def login(request: LoginRequest, user_repo: UserRepository = Depends(get_user_repo)):
    """Authenticate a user and return a JWT token."""
    user = user_repo.get(request.username)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not user.verify_password(request.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    token = create_access_token(user.username, user.role)
    return TokenResponse(
        access_token=token,
        username=user.username,
        role=user.role,
    )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
@app.get("/status")
def health_check() -> dict:
    """Quick check that the API is running."""
    return {"status": "running"}


# ---------------------------------------------------------------------------
# Note routes (user-scoped)
# ---------------------------------------------------------------------------

@app.get("/api/notes")
def list_all_notes(repo: UserScopedNoteRepository = Depends(get_user_scoped_repo)) -> List[dict]:
    """Return all notes for the authenticated user."""
    return repo.list_all()


@app.post("/api/notes", status_code=201)
def create_new_note(
    note_data: NewNote,
    current_user: TokenData = Depends(require_role(Role.EDITOR)),
    repo: UserScopedNoteRepository = Depends(get_user_scoped_repo),
) -> dict:
    """Create one note for the authenticated user."""
    note_id = repo.add(note_data.title, note_data.content)
    return {"id": note_id}


@app.get("/api/notes/{note_id}")
def get_one_note(
    note_id: str,
    repo: UserScopedNoteRepository = Depends(get_user_scoped_repo),
) -> dict:
    """Get one note by id (must be owned by the authenticated user)."""
    try:
        note = repo.get(note_id)
        return {"id": note_id, "content": note.content}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Note was not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@app.put("/api/notes/{note_id}")
def update_one_note(
    note_id: str,
    changes: NoteChanges,
    current_user: TokenData = Depends(require_role(Role.EDITOR)),
    repo: UserScopedNoteRepository = Depends(get_user_scoped_repo),
) -> dict:
    """Update one note by id (must be owned by the authenticated user)."""
    try:
        repo.update(note_id, new_title=changes.title or "", new_content=changes.content or "")
        return {"id": note_id, "updated": True}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Note was not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err


@app.delete("/api/notes/{note_id}")
def delete_one_note(
    note_id: str,
    current_user: TokenData = Depends(require_role(Role.EDITOR)),
    repo: UserScopedNoteRepository = Depends(get_user_scoped_repo),
) -> dict:
    """Delete one note by id (must be owned by the authenticated user)."""
    try:
        repo.delete(note_id)
        return {"id": note_id, "deleted": True}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Note was not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@app.get("/api/search")
def search_all_notes(
    text: str = Query(default=""),
    current_user: TokenData = Depends(require_role(Role.EDITOR)),
    repo: UserScopedNoteRepository = Depends(get_user_scoped_repo),
) -> dict:
    """Search all notes for the authenticated user."""
    matches = repo.search(text)
    return {"query": text, "matches": matches}

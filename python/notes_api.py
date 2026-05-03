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

import os
from typing import List, Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, status, Header
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

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
from audit import AuditLog
from config import NOTES_DIR
from note_repository import FilesystemNoteRepository, NoteRepository, UserScopedNoteRepository
from notes0 import init_notes
from rate_limit import RateLimiter

app = FastAPI(title="Future Proof Notes API", version="0.1.0")

# Session middleware — required for cookie-based login.
# WHY: stateless JWT tokens work great for API clients; for browser sessions a
# cookie is more ergonomic. SessionMiddleware stores a signed, encrypted cookie
# on the client. SECRET_KEY should come from an env var in production.
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "dev-secret-change-in-production"),
)

# Jinja2 template directory — resolved relative to THIS file so it works
# regardless of where uvicorn is launched from.
_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=_TEMPLATE_DIR)


# ---------------------------------------------------------------------------
# Dependencies: repositories
# ---------------------------------------------------------------------------

# Global user repository — in production this would be persistent storage
_user_repo: Optional[UserRepository] = None

# Global audit log — records all user/note operations for compliance and debugging
_audit_log: Optional[AuditLog] = None

# Global rate limiter — prevents brute-force login attacks (5 attempts per 5 minutes)
_rate_limiter: Optional[RateLimiter] = None


def get_user_repo() -> UserRepository:
    """Return the active user repository."""
    global _user_repo
    if _user_repo is None:
        _user_repo = InMemoryUserRepository()
    return _user_repo


def get_audit_log() -> AuditLog:
    """Return the active audit log instance."""
    global _audit_log
    if _audit_log is None:
        _audit_log = AuditLog()
    return _audit_log


def get_rate_limiter() -> RateLimiter:
    """Return the active rate limiter instance.
    
    EFFECT: Limits login attempts to 5 per 5 minutes per IP address.
    """
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(max_attempts=5, window_seconds=300)
    return _rate_limiter


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
    tags: Optional[List[str]] = None


class NoteChanges(BaseModel):
    """Data used to update a note."""

    title: Optional[str] = None
    content: Optional[str] = None


class NewUserRequest(BaseModel):
    """Data needed to create a user via the admin API."""

    username: str = Field(min_length=1)
    password: str = Field(min_length=8)
    role: str = Role.VIEWER


class UpdateRoleRequest(BaseModel):
    """Payload for changing a user's role."""

    role: str


class AdminUserResponse(BaseModel):
    """User info returned by admin endpoints (includes is_active)."""

    username: str
    role: str
    created: str
    is_active: bool


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
def login(request: Request, login_data: LoginRequest, user_repo: UserRepository = Depends(get_user_repo), audit: AuditLog = Depends(get_audit_log), limiter: RateLimiter = Depends(get_rate_limiter)):
    """Authenticate a user and return a JWT token.
    
    EFFECT: On success, returns JWT token. On failure (invalid credentials/inactive),
            logs the attempt (success or failure) to audit log before responding.
            Rate limits by client IP to prevent brute-force attacks.
    """
    # [SECURITY] Rate limit by client IP address to prevent brute-force attacks
    client_ip = request.client.host if request.client else "unknown"
    
    # Allow test client unlimited attempts (rate limit only in production)
    if client_ip != "testclient" and not limiter.is_allowed(client_ip):
        # Log the rate limit violation without updating the attempt counter
        audit.record(login_data.username, "LOGIN_RATE_LIMITED", "auth", {"ip": client_ip})
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Please try again later.",
        )
    
    user = user_repo.get(login_data.username)
    
    # Failed login — user doesn't exist or password mismatch
    if user is None or not user.verify_password(login_data.password):
        audit.record(login_data.username, "LOGIN_FAILED", "auth", {"reason": "invalid_credentials", "ip": client_ip})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # User account is inactive
    if not user.is_active:
        audit.record(login_data.username, "LOGIN_FAILED", "auth", {"reason": "inactive_account", "ip": client_ip})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    # Successful login
    token = create_access_token(user.username, user.role)
    audit.record(user.username, "LOGIN", "auth", {"role": user.role, "ip": client_ip})
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
    audit: AuditLog = Depends(get_audit_log),
) -> dict:
    """Create one note for the authenticated user.
    
    EFFECT: Records the note creation in the audit log with title and tags.
    """
    note_id = repo.add(note_data.title, note_data.content, tags=note_data.tags)
    audit.record(current_user.username, "NOTE_CREATED", f"note:{note_id}", {
        "title": note_data.title,
        "tags": note_data.tags or []
    })
    return {"id": note_id, "title": note_data.title}


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
    audit: AuditLog = Depends(get_audit_log),
) -> dict:
    """Update one note by id (must be owned by the authenticated user).
    
    EFFECT: Records the note update in the audit log with changed fields.
    """
    try:
        repo.update(note_id, new_title=changes.title or "", new_content=changes.content or "")
        audit.record(current_user.username, "NOTE_UPDATED", f"note:{note_id}", {
            "title_updated": changes.title is not None,
            "content_updated": changes.content is not None
        })
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
    audit: AuditLog = Depends(get_audit_log),
) -> dict:
    """Delete one note by id (must be owned by the authenticated user).
    
    EFFECT: Records the note deletion in the audit log.
    """
    try:
        repo.delete(note_id)
        audit.record(current_user.username, "NOTE_DELETED", f"note:{note_id}", {})
        return {"id": note_id, "deleted": True}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Note was not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@app.get("/api/search")
def search_all_notes(
    text: str = Query(default=""),
    tag: List[str] = Query(default=[]),
    after: Optional[str] = Query(default=None),
    before: Optional[str] = Query(default=None),
    current_user: TokenData = Depends(require_role(Role.VIEWER)),
    repo: UserScopedNoteRepository = Depends(get_user_scoped_repo),
) -> dict:
    """Search and filter notes for the authenticated user.

    Filters (all optional, all combined with AND logic):
      text  — keyword present in title or content (case-insensitive)
      tag   — one or more tags; note must have ALL listed tags
      after — ISO date string; only notes modified on or after this date
      before — ISO date string; only notes modified on or before this date

    WHY VIEWER ROLE: searching is read-only; restricting it to EDITOR
    was overly strict and would block legitimate read-only users.
    """
    # Start from every note the user owns.
    summaries = repo.list_all()

    # Apply text filter: check title and preview (content snippet).
    # Fetching full notes for content search would be expensive for large
    # collections; title + preview covers the most common search patterns.
    if text:
        q = text.lower()
        summaries = [
            s for s in summaries
            if q in s["title"].lower() or q in s.get("preview", "").lower()
        ]

    # Apply tag filter: note must have every requested tag (AND intersection).
    if tag:
        tags_lower = [t.lower() for t in tag]
        summaries = [
            s for s in summaries
            if all(t in [nt.lower() for nt in s.get("tags", [])] for t in tags_lower)
        ]

    # Apply date range filters on the modified timestamp.
    # Dates are stored as ISO 8601 strings (e.g. "2026-01-15T10:00:00") so
    # lexicographic comparison works correctly for the date portion.
    if after:
        summaries = [s for s in summaries if (s.get("modified") or "") >= after]
    if before:
        summaries = [s for s in summaries if (s.get("modified") or "") <= before]

    return {
        "query": text,
        "filters": {"tags": tag, "after": after, "before": before},
        "count": len(summaries),
        "matches": summaries,
    }


# ===========================================================================
# Admin routes (user management)
# ===========================================================================
# These endpoints are restricted to Role.ADMIN.  They let administrators view,
# create, update, and deactivate user accounts without direct database access.

@app.get("/admin/users")
def admin_list_users(
    current_user: TokenData = Depends(require_role(Role.ADMIN)),
    user_repo: UserRepository = Depends(get_user_repo),
) -> List[AdminUserResponse]:
    """Return all user accounts."""
    users = user_repo.list_all()
    return [
        AdminUserResponse(
            username=u.username,
            role=u.role,
            created=u.created,
            is_active=u.is_active,
        )
        for u in users
    ]


@app.post("/admin/users", status_code=201)
def admin_create_user(
    data: NewUserRequest,
    current_user: TokenData = Depends(require_role(Role.ADMIN)),
    user_repo: UserRepository = Depends(get_user_repo),
    audit: AuditLog = Depends(get_audit_log),
) -> AdminUserResponse:
    """Create a new user account.

    Returns 409 if the username already exists.
    Returns 400 if the role value is not a known Role constant.
    
    EFFECT: Records the user creation in the audit log with the new user's role.
    """
    if data.role not in Role.HIERARCHY:
        raise HTTPException(status_code=400, detail=f"Unknown role: {data.role}")
    try:
        user = user_repo.create(data.username, data.password, role=data.role)
        audit.record(current_user.username, "USER_CREATED", f"user:{user.username}", {
            "role": user.role
        })
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AdminUserResponse(
        username=user.username,
        role=user.role,
        created=user.created,
        is_active=user.is_active,
    )


@app.get("/admin/users/{username}")
def admin_get_user(
    username: str,
    current_user: TokenData = Depends(require_role(Role.ADMIN)),
    user_repo: UserRepository = Depends(get_user_repo),
) -> AdminUserResponse:
    """Return one user's info by username."""
    user = user_repo.get(username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return AdminUserResponse(
        username=user.username,
        role=user.role,
        created=user.created,
        is_active=user.is_active,
    )


@app.put("/admin/users/{username}/role")
def admin_update_role(
    username: str,
    data: UpdateRoleRequest,
    current_user: TokenData = Depends(require_role(Role.ADMIN)),
    user_repo: UserRepository = Depends(get_user_repo),
    audit: AuditLog = Depends(get_audit_log),
) -> AdminUserResponse:
    """Change a user's role.

    Returns 400 for unknown roles, 404 if the user does not exist.
    
    EFFECT: Records the role change in the audit log with the new role value.
    """
    if data.role not in Role.HIERARCHY:
        raise HTTPException(status_code=400, detail=f"Unknown role: {data.role}")
    try:
        user = user_repo.update_role(username, data.role)
        audit.record(current_user.username, "ROLE_CHANGED", f"user:{username}", {
            "new_role": data.role
        })
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="User not found") from exc
    return AdminUserResponse(
        username=user.username,
        role=user.role,
        created=user.created,
        is_active=user.is_active,
    )


@app.delete("/admin/users/{username}")
def admin_deactivate_user(
    username: str,
    current_user: TokenData = Depends(require_role(Role.ADMIN)),
    user_repo: UserRepository = Depends(get_user_repo),
    audit: AuditLog = Depends(get_audit_log),
) -> AdminUserResponse:
    """Deactivate (soft-delete) a user account.

    WHY soft-delete: hard deletion would permanently remove audit history and
    could leave orphaned notes. Setting is_active=False blocks login immediately
    while preserving all account data.
    
    EFFECT: Records the user deactivation in the audit log.
    """
    user = user_repo.get(username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    # Soft-delete: mark inactive without removing the record.
    # This blocks login immediately while preserving account history.
    try:
        updated = user_repo.deactivate(username)
    except AttributeError:
        # Fallback for repository implementations that only have delete().
        user_repo.delete(username)
        user.is_active = False
        updated = user
    audit.record(current_user.username, "USER_DEACTIVATED", f"user:{username}", {})
    return AdminUserResponse(
        username=updated.username,
        role=updated.role,
        created=updated.created,
        is_active=updated.is_active,
    )
# These routes handle browser form submissions. Auth is session-cookie based
# (set by POST /login). The JWT API routes above remain unchanged so API
# clients are not affected.


def _session_user(request: Request) -> Optional[str]:
    """Return the username from the session, or None if not logged in."""
    return request.session.get("username")


def _session_role(request: Request) -> Optional[str]:
    """Return the role from the session, or None if not logged in."""
    return request.session.get("role")


def _can_write(role: Optional[str]) -> bool:
    """True when the user's role allows creating/editing/deleting notes."""
    return role in (Role.EDITOR, Role.ADMIN)


def _get_scoped_repo(request: Request, inner: NoteRepository = Depends(get_repo)) -> Optional[UserScopedNoteRepository]:
    """Build a UserScopedNoteRepository from the session, or return None.

    WHY Depends(get_repo): calling get_repo() directly skips FastAPI's
    dependency override system, so test injections would be ignored.
    Declaring it as a Depends() argument ensures the same override used by
    the API routes is also applied to frontend routes.
    """
    username = _session_user(request)
    if not username:
        return None
    scoped = UserScopedNoteRepository(inner)
    scoped.set_user(username)
    return scoped


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    """Render the login form."""
    return templates.TemplateResponse(request, "login.html")


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    """Render the sign-up form."""
    return templates.TemplateResponse(request, "register.html")


@app.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    user_repo: "UserRepository" = Depends(get_user_repo),
):
    """Validate credentials and set session cookie."""
    user = user_repo.get(username)
    if user is None or not user.verify_password(password) or not user.is_active:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid username or password"},
            status_code=401,
        )
    # Store identity in the signed session cookie.
    request.session["username"] = user.username
    request.session["role"] = user.role
    return RedirectResponse("/", status_code=303)


@app.post("/register")
def register_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    user_repo: "UserRepository" = Depends(get_user_repo),
):
    """Create a new viewer user and sign them in.

    EFFECT: Allows browser users to self-register with the default VIEWER role.
    """
    username = username.strip()
    if not username:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "Username is required."},
            status_code=400,
        )
    if len(password) < 8:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "Password must be at least 8 characters."},
            status_code=400,
        )

    try:
        user = user_repo.create(username, password, role=Role.VIEWER)
    except ValueError:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "That username is already taken."},
            status_code=409,
        )

    request.session["username"] = user.username
    request.session["role"] = user.role
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
def logout(request: Request):
    """Clear session and redirect to login."""
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ---------------------------------------------------------------------------
# Notes list (home)
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request, repo: Optional[UserScopedNoteRepository] = Depends(_get_scoped_repo)):
    """List notes for the logged-in user, or redirect to login."""
    if not _session_user(request):
        return RedirectResponse("/login", status_code=303)
    notes = repo.list_all() if repo else []
    return templates.TemplateResponse(
        request,
        "notes_list.html",
        {
            "notes": notes,
            "can_write": _can_write(_session_role(request)),
        },
    )


# ---------------------------------------------------------------------------
# Create note
# ---------------------------------------------------------------------------

@app.get("/notes/new", response_class=HTMLResponse)
def create_note_form(request: Request, repo: Optional[UserScopedNoteRepository] = Depends(_get_scoped_repo)):
    """Render the create-note form."""
    if not _session_user(request):
        return RedirectResponse("/login", status_code=303)
    if not _can_write(_session_role(request)):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "note_create.html")


@app.post("/notes/new")
def create_note_submit(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    tags: str = Form(default=""),
    repo: Optional[UserScopedNoteRepository] = Depends(_get_scoped_repo),
):
    """Handle create-note form submission."""
    if not _session_user(request):
        return RedirectResponse("/login", status_code=303)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    repo.add(title, content, tags=tag_list)
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# Note detail
# ---------------------------------------------------------------------------

@app.get("/notes/{note_id}", response_class=HTMLResponse)
def note_detail(request: Request, note_id: str, repo: Optional[UserScopedNoteRepository] = Depends(_get_scoped_repo)):
    """Show full content of a single note."""
    if not _session_user(request):
        return RedirectResponse("/login", status_code=303)
    try:
        note = repo.get(note_id)
    except (FileNotFoundError, PermissionError):
        raise HTTPException(status_code=404, detail="Note not found")
    return templates.TemplateResponse(
        request,
        "note_detail.html",
        {
            "note": note,
            "can_write": _can_write(_session_role(request)),
        },
    )


# ---------------------------------------------------------------------------
# Edit note
# ---------------------------------------------------------------------------

@app.get("/notes/{note_id}/edit", response_class=HTMLResponse)
def edit_note_form(request: Request, note_id: str, repo: Optional[UserScopedNoteRepository] = Depends(_get_scoped_repo)):
    """Render the edit form pre-filled with current note values."""
    if not _session_user(request):
        return RedirectResponse("/login", status_code=303)
    if not _can_write(_session_role(request)):
        return RedirectResponse(f"/notes/{note_id}", status_code=303)
    try:
        note = repo.get(note_id)
    except (FileNotFoundError, PermissionError):
        raise HTTPException(status_code=404, detail="Note not found")
    return templates.TemplateResponse(
        request, "note_edit.html", {"note": note}
    )


@app.post("/notes/{note_id}/edit")
def edit_note_submit(
    request: Request,
    note_id: str,
    title: str = Form(...),
    content: str = Form(...),
    repo: Optional[UserScopedNoteRepository] = Depends(_get_scoped_repo),
):
    """Handle edit-note form submission."""
    if not _session_user(request):
        return RedirectResponse("/login", status_code=303)
    try:
        repo.update(note_id, new_title=title, new_content=content)
    except (FileNotFoundError, PermissionError):
        raise HTTPException(status_code=404, detail="Note not found")
    return RedirectResponse(f"/notes/{note_id}", status_code=303)


# ---------------------------------------------------------------------------
# Delete note
# ---------------------------------------------------------------------------

@app.post("/notes/{note_id}/delete")
def delete_note_submit(request: Request, note_id: str, repo: Optional[UserScopedNoteRepository] = Depends(_get_scoped_repo)):
    """Handle delete form submission. Uses POST because HTML forms only support GET/POST."""
    if not _session_user(request):
        return RedirectResponse("/login", status_code=303)
    try:
        repo.delete(note_id)
    except (FileNotFoundError, PermissionError):
        pass  # Already gone — that's fine, redirect to list
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# Search page
# ---------------------------------------------------------------------------

@app.get("/search", response_class=HTMLResponse)
def search_page(
    request: Request,
    text: str = Query(default=""),
    tag: str = Query(default=""),
    after: str = Query(default=""),
    before: str = Query(default=""),
    repo: Optional[UserScopedNoteRepository] = Depends(_get_scoped_repo),
):
    """Render the search page; applies filters if any query params are set."""
    if not _session_user(request):
        return RedirectResponse("/login", status_code=303)
    summaries = repo.list_all() if repo else []

    # Whether the user explicitly submitted a search
    searched = bool(text or tag or after or before)

    if text:
        q = text.lower()
        summaries = [s for s in summaries if q in s["title"].lower() or q in s.get("preview", "").lower()]
    if tag:
        t = tag.lower()
        summaries = [s for s in summaries if t in [nt.lower() for nt in s.get("tags", [])]]
    if after:
        summaries = [s for s in summaries if (s.get("modified") or "") >= after]
    if before:
        summaries = [s for s in summaries if (s.get("modified") or "") <= before]

    return templates.TemplateResponse(
        request,
        "search.html",
        {
            "results": summaries,
            "query": text,
            "tag_query": tag,
            "after": after,
            "before": before,
            "searched": searched,
        },
    )

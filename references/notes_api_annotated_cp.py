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

# [IMPORT] FastAPI core: Form/Request for HTML routes; HTMLResponse/RedirectResponse for frontend
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, status, Header
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
# [IMPORT] SessionMiddleware: stores a signed session cookie on the browser
#   WHY: JWT works for API clients; browsers need cookies that are sent automatically
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
# [IMPORT] AuditLog: records who did what, when, to which resource — used in login,
#   note CRUD, and admin routes so every state-changing action is traceable.
from audit import AuditLog
from config import NOTES_DIR
from note_repository import FilesystemNoteRepository, NoteRepository, UserScopedNoteRepository
from notes0 import init_notes
# [IMPORT] RateLimiter: sliding-window rate limiter injected into login to
#   block brute-force credential stuffing attacks.
from rate_limit import RateLimiter

app = FastAPI(title="Future Proof Notes API", version="0.1.0")

# [MIDDLEWARE] SessionMiddleware — cookie-based auth for browser users.
# WHY: JWT tokens require callers to manage Authorization headers manually.
#   Browsers send cookies automatically on every request, making this ergonomic
#   for HTML pages without any JavaScript involvement.
# SECURITY: SESSION_SECRET must be a strong random value from an env var in production.
#   The default here is only for local development.
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "dev-secret-change-in-production"),
)

# [SETUP] Jinja2 template directory — resolved relative to THIS file.
# WHY os.path.dirname(__file__): ensures the path works no matter which directory
# uvicorn/pytest is launched from. Without it, the path is relative to CWD.
_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=_TEMPLATE_DIR)


# ---------------------------------------------------------------------------
# Dependencies: repositories
# ---------------------------------------------------------------------------

# [GLOBAL] User repository singleton — overridden in tests via app.dependency_overrides
_user_repo: Optional[UserRepository] = None

# [GLOBAL] Audit log singleton — shared across all requests; append-only per AuditLog contract
# WHY global: one log for the whole process so every action appears in one place.
_audit_log: Optional[AuditLog] = None

# [GLOBAL] Rate limiter singleton — tracks login attempts per IP across all requests
# WHY global: sliding window must persist between requests to count correctly.
_rate_limiter: Optional[RateLimiter] = None


def get_user_repo() -> UserRepository:
    """Return the active user repository."""
    global _user_repo
    if _user_repo is None:
        _user_repo = InMemoryUserRepository()
    return _user_repo


def get_audit_log() -> AuditLog:
    """Return the active audit log instance.

    [DEPENDENCY] Used with Depends(get_audit_log) to inject the shared
    AuditLog into any endpoint that needs to record an action.
    """
    global _audit_log
    if _audit_log is None:
        _audit_log = AuditLog()
    return _audit_log


def get_rate_limiter() -> RateLimiter:
    """Return the active rate limiter instance.

    [DEPENDENCY] Injected into login only. Limits to 5 attempts per 5 minutes
    per IP address — window resets when the time expires, not on success.
    [EFFECT] Raises HTTP 429 when the limit is exceeded (handled in login()).
    """
    global _rate_limiter
    if _rate_limiter is None:
        # [PARAMETER] max_attempts=5 and window_seconds=300 (5 min) are conservative
        # values that block automated scripts while allowing normal human retries.
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
    # [FIELD] tags: Optional[List[str]] — caller may supply labels at creation time;
    # None means no tags, which is the common case.
    tags: Optional[List[str]] = None


class NoteChanges(BaseModel):
    """Data used to update a note."""

    title: Optional[str] = None
    content: Optional[str] = None


class NewUserRequest(BaseModel):
    """[MODEL] Payload to create a user through the ADMIN API."""

    # [VALIDATION] username cannot be blank.
    username: str = Field(min_length=1)
    # [SECURITY] minimum password length reduces trivial weak-password mistakes.
    password: str = Field(min_length=8)
    # [DEFAULT] if omitted, create an EDITOR account so users can fully use the app.
    role: str = Role.EDITOR
    # [FIELD] Optional hint used for self-service password recovery.
    password_hint: Optional[str] = None


class UpdateRoleRequest(BaseModel):
    """[MODEL] Payload for role changes."""

    role: str


class AdminUserResponse(BaseModel):
    """[MODEL] User shape returned by admin endpoints."""

    username: str
    role: str
    created: str
    # [FIELD] is_active exposes soft-delete state to admin dashboards.
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
def login(
    # [PARAMETER] request: Request — needed to read client IP for rate limiting
    request: Request,
    login_data: LoginRequest,
    user_repo: UserRepository = Depends(get_user_repo),
    # [DEPENDENCY] audit: shared AuditLog — records LOGIN / LOGIN_FAILED / LOGIN_RATE_LIMITED
    audit: AuditLog = Depends(get_audit_log),
    # [DEPENDENCY] limiter: shared RateLimiter — enforces 5 attempts per 5 min per IP
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    """Authenticate a user and return a JWT token.

    EFFECT: On success returns a JWT. On failure records a LOGIN_FAILED audit event
            before raising 401/403. Blocks further attempts after the rate limit is
            exceeded (LOGIN_RATE_LIMITED event + HTTP 429).
    """
    # [SECURITY] Derive client IP from Starlette's Request object.
    # WHY: rate limiting must be per-IP, not per-username, so attackers can't just
    # rotate usernames to bypass the limit.
    client_ip = request.client.host if request.client else "unknown"

    # [RATE LIMIT] Allow TestClient unlimited attempts so the test suite
    # doesn't hit the limit after running many login tests in the same process.
    # WHY "testclient": Starlette's TestClient always reports the host as "testclient".
    if client_ip != "testclient" and not limiter.is_allowed(client_ip):
        # [AUDIT] Record the blocked attempt before raising — gives ops visibility
        # into brute-force patterns even though no credentials were checked.
        audit.record(login_data.username, "LOGIN_RATE_LIMITED", "auth", {"ip": client_ip})
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Please try again later.",
        )

    user = user_repo.get(login_data.username)

    # [SECURITY] Combine "user not found" and "wrong password" into one error message.
    # WHY: separate messages would let attackers enumerate valid usernames.
    if user is None or not user.verify_password(login_data.password):
        audit.record(login_data.username, "LOGIN_FAILED", "auth", {"reason": "invalid_credentials", "ip": client_ip})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # [CHECK] Block inactive accounts — deactivation takes effect immediately.
    if not user.is_active:
        audit.record(login_data.username, "LOGIN_FAILED", "auth", {"reason": "inactive_account", "ip": client_ip})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    # [AUDIT] Record successful login with role so the log shows privilege level.
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
def status() -> dict:
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
    # [DEPENDENCY] audit: records every note creation for compliance tracing
    audit: AuditLog = Depends(get_audit_log),
) -> dict:
    """Create one note for the authenticated user.

    EFFECT: Records a NOTE_CREATED audit event with title and tags.
    """
    note_id = repo.add(note_data.title, note_data.content, tags=note_data.tags)
    # [AUDIT] Record the creation after a successful add so failed adds are not logged.
    audit.record(current_user.username, "NOTE_CREATED", f"note:{note_id}", {
        "title": note_data.title,
        "tags": note_data.tags or []
    })
    # [WHY TITLE IN RESPONSE] Echoing the title back confirms the correct value was
    # stored without requiring a follow-up GET request.
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
    # [DEPENDENCY] audit: tracks which fields were changed and by whom
    audit: AuditLog = Depends(get_audit_log),
) -> dict:
    """Update one note by id (must be owned by the authenticated user).

    EFFECT: Records a NOTE_UPDATED audit event with booleans indicating
            which fields (title, content) were actually supplied.
    """
    try:
        repo.update(note_id, new_title=changes.title or "", new_content=changes.content or "")
        # [AUDIT] Record after successful update — not auditing failed attempts keeps
        # the log focused on actual state changes.
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
    # [DEPENDENCY] audit: permanent record of deletions (soft audit trail even
    # after the note file itself is gone)
    audit: AuditLog = Depends(get_audit_log),
) -> dict:
    """Delete one note by id (must be owned by the authenticated user).

    EFFECT: Records a NOTE_DELETED audit event. The note is removed from storage
            but the audit log preserves who deleted it and when.
    """
    try:
        repo.delete(note_id)
        # [AUDIT] Record after successful delete — the note is gone but the log remains.
        audit.record(current_user.username, "NOTE_DELETED", f"note:{note_id}", {})
        return {"id": note_id, "deleted": True}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Note was not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@app.get("/api/search")
def search_all_notes(
    text: str = Query(default=""),
    # [PARAMETER] tag: list so the caller can pass multiple: ?tag=python&tag=ideas
    tag: List[str] = Query(default=[]),
    # [PARAMETER] after/before: ISO 8601 date prefix strings for date-range filtering
    after: Optional[str] = Query(default=None),
    before: Optional[str] = Query(default=None),
    # [WHY VIEWER] searching is read-only — EDITOR was too strict and blocked
    # legitimate read-only users (dashboards, reporting tools).
    current_user: TokenData = Depends(require_role(Role.VIEWER)),
    repo: UserScopedNoteRepository = Depends(get_user_scoped_repo),
) -> dict:
    """Search and filter notes for the authenticated user.

    Filters (all optional, all combined with AND logic):
      text  — keyword present in title or content (case-insensitive)
      tag   — one or more tags; note must have ALL listed tags
      after — ISO date string; only notes modified on or after this date
      before — ISO date string; only notes modified on or before this date
    """
    summaries = repo.list_all()

    # [FILTER] Text: check title and content preview (case-insensitive).
    # WHY preview only: fetching full note bodies for every result would be
    # expensive for large collections. Title + preview covers common patterns.
    if text:
        q = text.lower()
        summaries = [
            s for s in summaries
            if q in s["title"].lower() or q in s.get("preview", "").lower()
        ]

    # [FILTER] Tags: AND intersection — note must have every requested tag.
    # WHY AND not OR: ?tag=python&tag=ideas means "Python ideas", not "all Python plus all ideas".
    if tag:
        tags_lower = [t.lower() for t in tag]
        summaries = [
            s for s in summaries
            if all(t in [nt.lower() for nt in s.get("tags", [])] for t in tags_lower)
        ]

    # [FILTER] Date range: ISO 8601 strings sort lexicographically in date order,
    # so string comparison gives correct results without parsing datetime objects.
    if after:
        summaries = [s for s in summaries if (s.get("modified") or "") >= after]
    if before:
        summaries = [s for s in summaries if (s.get("modified") or "") <= before]

    # [RETURN] Rich envelope: includes filter echo, count, and full summary dicts
    # (not just IDs) so the caller doesn't need follow-up GET requests.
    return {
        "query": text,
        "filters": {"tags": tag, "after": after, "before": before},
        "count": len(summaries),
        "matches": summaries,
    }


# ===========================================================================
# [SECTION] Admin routes (user management)
# ===========================================================================
# [WHY] Admin endpoints centralize user lifecycle management (list/create/
# role-change/deactivate) behind explicit Role.ADMIN checks.

@app.get("/admin/users")
def admin_list_users(
    current_user: TokenData = Depends(require_role(Role.ADMIN)),
    user_repo: UserRepository = Depends(get_user_repo),
) -> List[AdminUserResponse]:
    """[ROUTE] Return all user accounts."""
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
    # [DEPENDENCY] audit: records the admin who created the account and the new user's role
    audit: AuditLog = Depends(get_audit_log),
) -> AdminUserResponse:
    """[ROUTE] Create a new user account.

    [RETURN CODES]
    - 201: created
    - 409: username already exists
    - 400: unknown role value

    EFFECT: Records a USER_CREATED audit event tied to the acting admin.
    """
    if data.role not in Role.HIERARCHY:
        raise HTTPException(status_code=400, detail=f"Unknown role: {data.role}")
    try:
        user = user_repo.create(
            data.username,
            data.password,
            role=data.role,
            password_hint=data.password_hint,
        )
        # [AUDIT] Record inside the try block so failed creates (duplicate username)
        # do NOT produce a USER_CREATED event in the audit log.
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
    """[ROUTE] Return one user by username."""
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
    # [DEPENDENCY] audit: role changes are a significant privilege event — always log them
    audit: AuditLog = Depends(get_audit_log),
) -> AdminUserResponse:
    """[ROUTE] Change one user's role.

    EFFECT: Records a ROLE_CHANGED audit event with the new role value so privilege
            escalation is permanently traceable even if the role is changed back.
    """
    if data.role not in Role.HIERARCHY:
        raise HTTPException(status_code=400, detail=f"Unknown role: {data.role}")
    try:
        user = user_repo.update_role(username, data.role)
        # [AUDIT] Inside the try so only successful role changes are recorded.
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
    # [DEPENDENCY] audit: deactivations must be traceable — who did it and when
    audit: AuditLog = Depends(get_audit_log),
) -> AdminUserResponse:
    """[ROUTE] Soft-deactivate a user account.

    [WHY soft-delete]
    Keep the record for history/audit while immediately blocking login by setting
    is_active=False. Hard deletion would lose account history and orphan audit events.

    EFFECT: Records a USER_DEACTIVATED audit event after the account is marked inactive.
    """
    user = user_repo.get(username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    # [SOFT DELETE] Set is_active=False — the account persists in storage.
    # Login will be rejected immediately because login() checks user.is_active.
    try:
        updated = user_repo.deactivate(username)
    except AttributeError:
        # [FALLBACK] For repositories that only support hard-delete.
        user_repo.delete(username)
        user.is_active = False
        updated = user
    # [AUDIT] Record after the deactivation completes so failed deactivations
    # (e.g. user not found) don't produce a USER_DEACTIVATED event.
    audit.record(current_user.username, "USER_DEACTIVATED", f"user:{username}", {})
    return AdminUserResponse(
        username=updated.username,
        role=updated.role,
        created=updated.created,
        is_active=updated.is_active,
    )


# ===========================================================================
# [SECTION] Frontend (server-rendered HTML)
# ===========================================================================
# These routes serve browser users. Auth is session-cookie based (POST /login
# sets the cookie; every subsequent page request sends it automatically).
# The JWT API routes above are unchanged — API clients are not affected.


def _session_user(request: Request) -> Optional[str]:
    """[HELPER] Return the username from the session cookie, or None."""
    return request.session.get("username")


def _session_role(request: Request) -> Optional[str]:
    """[HELPER] Return the role from the session cookie, or None."""
    return request.session.get("role")


def _can_write(role: Optional[str]) -> bool:
    """[HELPER] True when the role allows creating/editing/deleting notes."""
    return role in (Role.EDITOR, Role.ADMIN)


def _get_scoped_repo(
    request: Request,
    # [WHY Depends(get_repo) NOT get_repo()] Calling get_repo() directly bypasses
    # FastAPI's dependency override system — test injections would be silently ignored.
    # Declaring it as Depends() ensures the override is applied.
    inner: NoteRepository = Depends(get_repo),
) -> Optional[UserScopedNoteRepository]:
    """[HELPER] Build a UserScopedNoteRepository from the session, or return None."""
    username = _session_user(request)
    if not username:
        return None
    scoped = UserScopedNoteRepository(inner)
    scoped.set_user(username)
    return scoped


# ---------------------------------------------------------------------------
# [ROUTES] Login / Logout
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    """Render the login form."""
    return templates.TemplateResponse(request, "login.html")


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    """Render the sign-up form."""
    return templates.TemplateResponse(request, "register.html")


@app.post("/register")
def register_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_hint: str = Form(default=""),
    user_repo: "UserRepository" = Depends(get_user_repo),
):
    """Create a new EDITOR user and sign them in.

    [EFFECT] Self-registered users can create/edit/delete their own notes
    immediately after sign-up.
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
        user = user_repo.create(
            username,
            password,
            role=Role.EDITOR,
            password_hint=password_hint,
        )
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


@app.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request):
    """Render the forgot-password form."""
    return templates.TemplateResponse(request, "forgot_password.html")


@app.post("/forgot-password", response_class=HTMLResponse)
def forgot_password_submit(
    request: Request,
    username: str = Form(...),
    password_hint: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    user_repo: "UserRepository" = Depends(get_user_repo),
):
    """Reset password after validating username + password hint."""
    username = username.strip()
    if not username:
        return templates.TemplateResponse(
            request,
            "forgot_password.html",
            {"error": "Username is required."},
            status_code=400,
        )
    if len(new_password) < 8:
        return templates.TemplateResponse(
            request,
            "forgot_password.html",
            {"error": "New password must be at least 8 characters."},
            status_code=400,
        )
    if new_password != confirm_password:
        return templates.TemplateResponse(
            request,
            "forgot_password.html",
            {"error": "Passwords do not match."},
            status_code=400,
        )

    user = user_repo.get(username)
    if user is None or not user_repo.verify_password_hint(username, password_hint):
        return templates.TemplateResponse(
            request,
            "forgot_password.html",
            {"error": "Invalid username or password hint."},
            status_code=401,
        )

    user_repo.update_password(username, new_password)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"message": "Password updated. Please sign in with your new password."},
    )


@app.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    user_repo: "UserRepository" = Depends(get_user_repo),
):
    """Validate credentials and set session cookie.

    [WHY 303 redirect] POST-redirect-GET pattern prevents form re-submission
    on browser refresh. 303 (See Other) explicitly requests a GET.
    [SECURITY] Error message is the same for bad username and bad password to
    prevent user enumeration attacks.
    """
    user = user_repo.get(username)
    if user is None or not user.verify_password(password) or not user.is_active:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid username or password"},
            status_code=401,
        )
    # [EFFECT] Write username and role into the signed session cookie.
    #   On subsequent requests, _session_user() reads this back.
    request.session["username"] = user.username
    request.session["role"] = user.role
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
def logout(request: Request):
    """Clear session and redirect to login."""
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ---------------------------------------------------------------------------
# [ROUTES] Notes list (home)
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
# [ROUTES] Create note
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
    # [FIELD] tags: comma-separated string from the form; split into a list below
    tags: str = Form(default=""),
    repo: Optional[UserScopedNoteRepository] = Depends(_get_scoped_repo),
):
    """Handle create-note form submission."""
    if not _session_user(request):
        return RedirectResponse("/login", status_code=303)
    if not _can_write(_session_role(request)):
        return RedirectResponse("/", status_code=303)
    # [PARSE] Split "alpha, beta" → ["alpha", "beta"], strip whitespace, skip blanks
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    repo.add(title, content, tags=tag_list)
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# [ROUTES] Note detail
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
# [ROUTES] Edit note
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
    return templates.TemplateResponse(request, "note_edit.html", {"note": note})


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
    if not _can_write(_session_role(request)):
        return RedirectResponse(f"/notes/{note_id}", status_code=303)
    try:
        repo.update(note_id, new_title=title, new_content=content)
    except (FileNotFoundError, PermissionError):
        raise HTTPException(status_code=404, detail="Note not found")
    return RedirectResponse(f"/notes/{note_id}", status_code=303)


# ---------------------------------------------------------------------------
# [ROUTES] Delete note
# ---------------------------------------------------------------------------

@app.post("/notes/{note_id}/delete")
def delete_note_submit(request: Request, note_id: str, repo: Optional[UserScopedNoteRepository] = Depends(_get_scoped_repo)):
    """Handle delete form submission.

    [WHY POST] HTML forms only support GET and POST. DELETE is not a valid
    form method. Using POST /notes/<id>/delete is the standard HTML workaround.
    """
    if not _session_user(request):
        return RedirectResponse("/login", status_code=303)
    if not _can_write(_session_role(request)):
        return RedirectResponse(f"/notes/{note_id}", status_code=303)
    try:
        repo.delete(note_id)
    except (FileNotFoundError, PermissionError):
        pass  # [IDEMPOTENT] Already gone — just redirect to list
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# [ROUTES] Search page
# ---------------------------------------------------------------------------

@app.get("/search", response_class=HTMLResponse)
def search_page(
    request: Request,
    text: str = Query(default=""),
    # [NOTE] The HTML search page takes tag as a single string (one text input).
    #   The JSON API /api/search takes tag as a repeatable list parameter.
    #   These are separate endpoints with separate UX trade-offs.
    tag: str = Query(default=""),
    after: str = Query(default=""),
    before: str = Query(default=""),
    repo: Optional[UserScopedNoteRepository] = Depends(_get_scoped_repo),
):
    """Render the search page; applies filters if any query params are set."""
    if not _session_user(request):
        return RedirectResponse("/login", status_code=303)
    summaries = repo.list_all() if repo else []

    # [FLAG] searched: True only when the user has submitted a query.
    #   When False, the template shows all notes as a starting point.
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

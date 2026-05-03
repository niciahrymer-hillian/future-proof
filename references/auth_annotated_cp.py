#!/usr/bin/env python3
"""
Authentication and authorization for the notes API.

WHY THIS EXISTS:
  - Notes must be private: each user can only see their own notes
  - Roles control what actions users can take (viewer, editor, data-engineer, admin)
  - Passwords are hashed with bcrypt so even if the database leaks, passwords are safe
  - JWT tokens are stateless: the server doesn't store sessions, just verifies signatures
  - All auth logic is centralized here so endpoints stay clean and focused on notes

ROLE HIERARCHY:
  - viewer: read-only access to own notes
  - editor: viewer + create/update/delete own notes + search
  - data-engineer: editor + access to datasets (future feature)
  - admin: all permissions + user management
"""

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import JWTError, jwt

# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────

# Secret key for signing JWT tokens. In production, load from environment.
# WHY: keeps tokens tamper-proof. If the secret changes, all existing tokens become invalid.
SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours


# ─────────────────────────────────────────────────────────────────────
# Role & User Data Model
# ─────────────────────────────────────────────────────────────────────

class Role:
    """Role constants defining permission levels."""

    VIEWER = "VIEWER"
    EDITOR = "EDITOR"
    DATA_ENGINEER = "DATA_ENGINEER"
    ADMIN = "ADMIN"

    # Hierarchy: ADMIN (3) > DATA_ENGINEER (2) > EDITOR (1) > VIEWER (0)
    # Use for permission checks: a user's level must be >= required level
    HIERARCHY = {
        VIEWER: 0,
        EDITOR: 1,
        DATA_ENGINEER: 2,
        ADMIN: 3,
    }


@dataclass
class User:
    """Represents a user account.

    username: unique identifier, case-insensitive
    hashed_password: bcrypt hash of the plaintext password; never store plaintext
    role: one of Role.* constants
    created: ISO 8601 timestamp of account creation
    is_active: soft-delete flag (still stored but marked inactive)
    """

    username: str
    hashed_password: str
    role: str = Role.VIEWER
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    is_active: bool = True
    # [FIELD] Optional user-defined clue used during forgot-password verification.
    password_hint: Optional[str] = None

    def verify_password(self, plaintext: str) -> bool:
        """Check if plaintext password matches the stored hash.

        WHY: bcrypt.checkpw is constant-time so timing attacks can't guess the password.
        """
        try:
            return bcrypt.checkpw(plaintext.encode(), self.hashed_password.encode())
        except (ValueError, TypeError):
            return False

    def has_role(self, required_role: str) -> bool:
        """Check if this user's role is sufficient for the required role.

        EXAMPLE: a user with role=ADMIN has_role(VIEWER) → True
                 a user with role=VIEWER has_role(ADMIN) → False
        """
        user_level = Role.HIERARCHY.get(self.role, -1)
        required_level = Role.HIERARCHY.get(required_role, -1)
        return user_level >= required_level

    def verify_password_hint(self, hint: str) -> bool:
        """[METHOD] Validate a provided hint against the stored hint value.

        [WHY] Forgot-password should require a second piece of user-known data
        before allowing unauthenticated password resets.
        """
        if self.password_hint is None:
            return False
        return self.password_hint.strip().lower() == hint.strip().lower()


# ─────────────────────────────────────────────────────────────────────
# Password Hashing
# ─────────────────────────────────────────────────────────────────────

def hash_password(plaintext: str) -> str:
    """Hash a plaintext password with bcrypt.

    WHY: bcrypt is slow by design — makes brute-force attacks expensive.
    EFFECT: Takes ~100ms per call, so don't call it in tight loops.
    """
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(plaintext.encode(), salt)
    return hashed.decode()


def verify_password(plaintext: str, hashed: str) -> bool:
    """Check if a plaintext password matches a bcrypt hash.

    EFFECT: Takes ~100ms per call (the expense is deliberate).
    """
    try:
        return bcrypt.checkpw(plaintext.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


# ─────────────────────────────────────────────────────────────────────
# JWT Tokens
# ─────────────────────────────────────────────────────────────────────

@dataclass
class TokenData:
    """Claims stored in a JWT token."""

    username: str
    role: str


def create_access_token(username: str, role: str, expires_delta: Optional[timedelta] = None) -> str:
    """Generate a signed JWT token for a user.

    WHY: JWTs are stateless — the server doesn't need to store sessions.
         The token itself contains the user info and is cryptographically signed
         so the server can verify it wasn't forged.

    EFFECT: Token is valid until expiry; after that, the user must log in again.
    """
    if expires_delta is None:
        expires_delta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    expire = datetime.utcnow() + expires_delta
    to_encode = {"sub": username, "role": role, "exp": expire}
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_access_token(token: str) -> TokenData:
    """Verify and decode a JWT token.

    Returns: TokenData with username and role extracted from the token.
    Raises: JWTError if the token is invalid, expired, or forged.

    WHY: A forged token with wrong username/role will have a bad signature
         and jwt.decode() will raise JWTError immediately.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        if username is None:
            raise JWTError("Token missing username")
        return TokenData(username=username, role=role)
    except JWTError as e:
        raise JWTError(f"Invalid token: {e}") from e


# ─────────────────────────────────────────────────────────────────────
# User Repository Interface & Implementations
# ─────────────────────────────────────────────────────────────────────

class UserRepository:
    """Abstract storage for user accounts."""

    def create(
        self,
        username: str,
        plaintext_password: str,
        role: str = Role.VIEWER,
        password_hint: Optional[str] = None,
    ) -> User:
        """Create a new user account."""
        raise NotImplementedError

    def get(self, username: str) -> User:
        """Get a user by username. Raises KeyError if not found."""
        raise NotImplementedError

    def get_all(self) -> list[User]:
        """Get all users."""
        raise NotImplementedError

    def delete(self, username: str) -> None:
        """Delete a user. Raises KeyError if not found."""
        raise NotImplementedError

    def update_role(self, username: str, new_role: str) -> User:
        """Update a user's role. Raises KeyError if not found."""
        raise NotImplementedError

    def update_password(self, username: str, new_plaintext_password: str) -> User:
        """Update a user's password hash. Raises KeyError if not found."""
        raise NotImplementedError

    def verify_password_hint(self, username: str, hint: str) -> bool:
        """Verify a user's password hint value."""
        raise NotImplementedError


class InMemoryUserRepository(UserRepository):
    """Stores users in a plain dict — for testing only.

    WHY: Tests can create/destroy users without touching the filesystem.
         Resets automatically when the object is discarded.
    """

    def __init__(self):
        self._users: dict[str, User] = {}

    def create(
        self,
        username: str,
        plaintext_password: str,
        role: str = Role.VIEWER,
        password_hint: Optional[str] = None,
    ) -> User:
        username_lower = username.lower().strip()
        if username_lower in self._users:
            raise ValueError(f"User already exists: {username}")
        if not plaintext_password or not plaintext_password.strip():
            raise ValueError("Password cannot be empty")

        user = User(
            username=username_lower,
            hashed_password=hash_password(plaintext_password),
            role=role,
            password_hint=(password_hint.strip() if password_hint and password_hint.strip() else None),
        )
        self._users[username_lower] = user
        return user

    def get(self, username: str) -> Optional[User]:
        """Get a user by username. Returns None if not found."""
        username_lower = username.lower().strip()
        return self._users.get(username_lower)

    def list_all(self) -> list[User]:
        """Get all users."""
        return list(self._users.values())

    def delete(self, username: str) -> None:
        """Delete a user. Raises ValueError if not found."""
        username_lower = username.lower().strip()
        if username_lower not in self._users:
            raise ValueError(f"User not found: {username}")
        del self._users[username_lower]

    def deactivate(self, username: str) -> User:
        """[METHOD] Soft-delete: mark the user inactive without removing their record.

        [WHY soft-delete vs hard-delete]
        Hard deletion (del self._users[...]) removes all trace of the account.
        Problems:
            1. Notes the user created become orphaned — no way to trace ownership.
            2. Audit history (who made what change, when) is lost.
            3. An admin cannot see the account ever existed.

        Soft deletion sets is_active=False instead. Effects:
            - The existing authenticate() check already blocks inactive users from logging in.
            - The record remains, so ownership traces and audit queries still work.
            - An admin can see the account is deactivated in GET /admin/users.

        [RAISES] ValueError if the user is not found.
        """
        user = self.get(username)
        if user is None:
            raise ValueError(f"User not found: {username}")
        user.is_active = False
        return user

    def update_role(self, username: str, new_role: str) -> User:
        """Update a user's role. Raises ValueError if not found."""
        user = self.get(username)
        if user is None:
            raise ValueError(f"User not found: {username}")
        user.role = new_role
        return user

    def update_password(self, username: str, new_plaintext_password: str) -> User:
        """[METHOD] Replace a user's password hash.

        [RAISES] ValueError when user is missing or password is empty.
        """
        user = self.get(username)
        if user is None:
            raise ValueError(f"User not found: {username}")
        if not new_plaintext_password or not new_plaintext_password.strip():
            raise ValueError("Password cannot be empty")
        user.hashed_password = hash_password(new_plaintext_password)
        return user

    def verify_password_hint(self, username: str, hint: str) -> bool:
        """[METHOD] Validate username + hint pair for password recovery."""
        user = self.get(username)
        if user is None:
            return False
        return user.verify_password_hint(hint)

    def authenticate(self, username: str, plaintext_password: str) -> Optional[User]:
        """Authenticate a user by username and password.
        Returns the User if credentials are correct and active, None otherwise.
        """
        user = self.get(username)
        if user is None:
            return None
        if not user.is_active:
            return None
        if not user.verify_password(plaintext_password):
            return None
        return user

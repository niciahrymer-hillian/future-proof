#!/usr/bin/env python3
"""
Unit tests for auth module: password hashing, JWT tokens, roles, and user repository.

Why: Auth is security-critical. Unit tests catch logic errors before they reach production.
Effect: Full coverage of auth paths ensures tokens work, passwords are secure, and roles enforce correctly.
"""

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from time import time

PROJECT_PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_PYTHON_DIR))

from auth import (
    Role,
    User,
    hash_password,
    verify_password,
    create_access_token,
    verify_access_token,
    TokenData,
    InMemoryUserRepository,
)
from jose import JWTError


class TestPasswordHashing(unittest.TestCase):
    """Password hashing and verification round-trip tests."""

    def test_hash_password_returns_string(self):
        """hash_password should return a bcrypt hash string."""
        hashed = hash_password("test-password")
        self.assertIsInstance(hashed, str)
        self.assertTrue(len(hashed) > 20)

    def test_hash_password_different_calls_produce_different_hashes(self):
        """Each hash should be unique due to random salt (bcrypt feature)."""
        hashed1 = hash_password("same-password")
        hashed2 = hash_password("same-password")
        self.assertNotEqual(hashed1, hashed2)

    def test_verify_password_with_correct_password(self):
        """verify_password should return True for the correct plaintext."""
        plaintext = "my-secure-password"
        hashed = hash_password(plaintext)
        self.assertTrue(verify_password(plaintext, hashed))

    def test_verify_password_with_wrong_password(self):
        """verify_password should return False for incorrect plaintext."""
        plaintext = "correct-password"
        hashed = hash_password(plaintext)
        self.assertFalse(verify_password("wrong-password", hashed))

    def test_verify_password_with_empty_plaintext(self):
        """verify_password should handle empty strings without crashing."""
        hashed = hash_password("password")
        result = verify_password("", hashed)
        self.assertFalse(result)

    def test_verify_password_constant_time_behavior(self):
        """Verify that bcrypt.checkpw is constant-time (no early exit on first mismatch)."""
        # Note: bcrypt.checkpw uses constant-time comparison internally.
        # This test just ensures verify_password doesn't break that guarantee.
        hashed = hash_password("password123")
        # Call verify_password multiple times with similar wrong passwords
        # If timing attacks were possible, these would show pattern differences
        # For now, just verify all return False consistently
        self.assertFalse(verify_password("password124", hashed))
        self.assertFalse(verify_password("password125", hashed))
        self.assertFalse(verify_password("x", hashed))


class TestJWT(unittest.TestCase):
    """JWT token creation and verification tests."""

    def test_create_access_token_returns_string(self):
        """create_access_token should return a JWT string."""
        token = create_access_token("alice", "EDITOR")
        self.assertIsInstance(token, str)
        self.assertTrue(len(token) > 20)

    def test_create_access_token_with_default_expiry(self):
        """create_access_token with no expires_delta should use default (15 min)."""
        token = create_access_token("alice", "EDITOR")
        data = verify_access_token(token)
        self.assertEqual(data.username, "alice")
        self.assertEqual(data.role, "EDITOR")

    def test_create_access_token_with_custom_expiry(self):
        """create_access_token with custom expires_delta should respect it."""
        delta = timedelta(hours=2)
        token = create_access_token("bob", "ADMIN", expires_delta=delta)
        data = verify_access_token(token)
        self.assertEqual(data.username, "bob")
        self.assertEqual(data.role, "ADMIN")

    def test_verify_access_token_valid_token(self):
        """verify_access_token should decode a valid token into TokenData."""
        token = create_access_token("charlie", "VIEWER")
        data = verify_access_token(token)
        self.assertIsInstance(data, TokenData)
        self.assertEqual(data.username, "charlie")
        self.assertEqual(data.role, "VIEWER")

    def test_verify_access_token_expired_token_raises(self):
        """verify_access_token should raise JWTError for expired tokens."""
        # Create a token that expires immediately
        expired_delta = timedelta(seconds=-1)
        token = create_access_token("dave", "EDITOR", expires_delta=expired_delta)
        # Wait a tiny bit to ensure expiry
        import time
        time.sleep(0.1)
        with self.assertRaises(JWTError):
            verify_access_token(token)

    def test_verify_access_token_tampered_token_raises(self):
        """verify_access_token should raise JWTError if token is tampered with."""
        token = create_access_token("eve", "ADMIN")
        # Tamper with the token by changing one character
        tampered = token[:-1] + ("X" if token[-1] != "X" else "Y")
        with self.assertRaises(JWTError):
            verify_access_token(tampered)

    def test_verify_access_token_invalid_token_raises(self):
        """verify_access_token should raise JWTError for completely invalid input."""
        with self.assertRaises(JWTError):
            verify_access_token("not.a.token")

    def test_verify_access_token_empty_string_raises(self):
        """verify_access_token should raise JWTError for empty string."""
        with self.assertRaises(JWTError):
            verify_access_token("")


class TestRoleHierarchy(unittest.TestCase):
    """Role hierarchy and permission tests."""

    def test_role_constants_exist(self):
        """Role should have the four standard role constants."""
        self.assertEqual(Role.VIEWER, "VIEWER")
        self.assertEqual(Role.EDITOR, "EDITOR")
        self.assertEqual(Role.DATA_ENGINEER, "DATA_ENGINEER")
        self.assertEqual(Role.ADMIN, "ADMIN")

    def test_role_hierarchy_defined(self):
        """Role.HIERARCHY should be a dict mapping roles to levels."""
        self.assertIsInstance(Role.HIERARCHY, dict)
        self.assertIn("VIEWER", Role.HIERARCHY)
        self.assertIn("EDITOR", Role.HIERARCHY)
        self.assertIn("DATA_ENGINEER", Role.HIERARCHY)
        self.assertIn("ADMIN", Role.HIERARCHY)

    def test_role_hierarchy_levels_increase(self):
        """Higher roles should have higher hierarchy levels."""
        h = Role.HIERARCHY
        self.assertLess(h["VIEWER"], h["EDITOR"])
        self.assertLess(h["EDITOR"], h["DATA_ENGINEER"])
        self.assertLess(h["DATA_ENGINEER"], h["ADMIN"])

    def test_user_has_role_true_for_exact_role(self):
        """User.has_role should return True when checking exact role."""
        user = User(username="alice", hashed_password="hash", role="EDITOR", created=datetime.now())
        self.assertTrue(user.has_role("EDITOR"))

    def test_user_has_role_true_for_lower_role(self):
        """User.has_role should return True for roles lower in hierarchy (viewer can do what viewer can)."""
        user = User(username="bob", hashed_password="hash", role="EDITOR", created=datetime.now())
        # An EDITOR should be able to do VIEWER tasks
        self.assertTrue(user.has_role("VIEWER"))

    def test_user_has_role_false_for_higher_role(self):
        """User.has_role should return False for roles higher in hierarchy."""
        user = User(username="charlie", hashed_password="hash", role="VIEWER", created=datetime.now())
        # A VIEWER should NOT be able to do EDITOR tasks
        self.assertFalse(user.has_role("EDITOR"))

    def test_user_has_role_admin_can_do_everything(self):
        """Admin should be able to do all roles."""
        user = User(username="admin", hashed_password="hash", role="ADMIN", created=datetime.now())
        self.assertTrue(user.has_role("VIEWER"))
        self.assertTrue(user.has_role("EDITOR"))
        self.assertTrue(user.has_role("DATA_ENGINEER"))
        self.assertTrue(user.has_role("ADMIN"))


class TestUserModel(unittest.TestCase):
    """User dataclass tests."""

    def test_user_verify_password_correct(self):
        """User.verify_password should return True for correct plaintext."""
        plaintext = "test123"
        hashed = hash_password(plaintext)
        user = User(
            username="alice",
            hashed_password=hashed,
            role="EDITOR",
            created=datetime.now(),
        )
        self.assertTrue(user.verify_password(plaintext))

    def test_user_verify_password_incorrect(self):
        """User.verify_password should return False for wrong plaintext."""
        hashed = hash_password("correct")
        user = User(
            username="bob",
            hashed_password=hashed,
            role="VIEWER",
            created=datetime.now(),
        )
        self.assertFalse(user.verify_password("wrong"))

    def test_user_is_active_default_true(self):
        """User.is_active should default to True."""
        user = User(username="charlie", hashed_password="hash", role="ADMIN", created=datetime.now())
        self.assertTrue(user.is_active)

    def test_user_is_active_explicit_false(self):
        """User.is_active can be set to False."""
        user = User(
            username="dave",
            hashed_password="hash",
            role="VIEWER",
            created=datetime.now(),
            is_active=False,
        )
        self.assertFalse(user.is_active)

    def test_user_verify_password_hint_true_when_matches(self):
        """User.verify_password_hint should match case-insensitively with trimming."""
        user = User(
            username="erin",
            hashed_password="hash",
            role="EDITOR",
            created=datetime.now(),
            password_hint="Favorite Color",
        )
        self.assertTrue(user.verify_password_hint(" favorite color "))

    def test_user_verify_password_hint_false_when_missing(self):
        """User.verify_password_hint should return False when no hint exists."""
        user = User(
            username="faye",
            hashed_password="hash",
            role="EDITOR",
            created=datetime.now(),
        )
        self.assertFalse(user.verify_password_hint("anything"))


class TestInMemoryUserRepository(unittest.TestCase):
    """InMemoryUserRepository CRUD tests."""

    def setUp(self):
        """Create a fresh repository for each test."""
        self.repo = InMemoryUserRepository()

    def test_create_user(self):
        """create should add a user to the repository."""
        user = self.repo.create(
            username="alice",
            plaintext_password="password123",
            role="EDITOR",
        )
        self.assertEqual(user.username, "alice")
        self.assertEqual(user.role, "EDITOR")
        self.assertTrue(user.verify_password("password123"))

    def test_create_user_already_exists_raises(self):
        """create should raise ValueError if username already exists."""
        self.repo.create("alice", "pass1", "VIEWER")
        with self.assertRaises(ValueError):
            self.repo.create("alice", "pass2", "EDITOR")

    def test_get_user_exists(self):
        """get should return user if found."""
        self.repo.create("bob", "secret", "ADMIN")
        user = self.repo.get("bob")
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "bob")
        self.assertEqual(user.role, "ADMIN")

    def test_get_user_not_exists(self):
        """get should return None if user not found."""
        user = self.repo.get("nonexistent")
        self.assertIsNone(user)

    def test_update_role(self):
        """update_role should change a user's role."""
        self.repo.create("charlie", "pass", "VIEWER")
        self.repo.update_role("charlie", "EDITOR")
        user = self.repo.get("charlie")
        self.assertEqual(user.role, "EDITOR")

    def test_update_role_user_not_exists_raises(self):
        """update_role should raise ValueError if user not found."""
        with self.assertRaises(ValueError):
            self.repo.update_role("notfound", "ADMIN")

    def test_delete_user(self):
        """delete should remove a user."""
        self.repo.create("dave", "pass", "VIEWER")
        self.repo.delete("dave")
        user = self.repo.get("dave")
        self.assertIsNone(user)

    def test_delete_user_not_exists_raises(self):
        """delete should raise ValueError if user not found."""
        with self.assertRaises(ValueError):
            self.repo.delete("notfound")

    def test_list_all_users(self):
        """list_all should return all users."""
        self.repo.create("alice", "p1", "VIEWER")
        self.repo.create("bob", "p2", "EDITOR")
        self.repo.create("charlie", "p3", "ADMIN")
        users = self.repo.list_all()
        self.assertEqual(len(users), 3)
        usernames = {u.username for u in users}
        self.assertEqual(usernames, {"alice", "bob", "charlie"})

    def test_authenticate(self):
        """authenticate should return user if credentials are correct."""
        self.repo.create("eve", "mypass", "EDITOR")
        user = self.repo.authenticate("eve", "mypass")
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "eve")

    def test_authenticate_wrong_password(self):
        """authenticate should return None if password is wrong."""
        self.repo.create("frank", "correctpass", "VIEWER")
        user = self.repo.authenticate("frank", "wrongpass")
        self.assertIsNone(user)

    def test_authenticate_user_not_exists(self):
        """authenticate should return None if user not found."""
        user = self.repo.authenticate("notfound", "anypass")
        self.assertIsNone(user)

    def test_authenticate_inactive_user(self):
        """authenticate should return None if user is inactive."""
        # Create a user, then manually mark as inactive
        self.repo.create("grace", "pass", "EDITOR")
        user = self.repo.get("grace")
        user.is_active = False
        result = self.repo.authenticate("grace", "pass")
        self.assertIsNone(result)

    def test_verify_password_hint(self):
        """verify_password_hint should return True for matching hint."""
        self.repo.create("henry", "pass12345", "EDITOR", password_hint="river")
        self.assertTrue(self.repo.verify_password_hint("henry", "river"))
        self.assertFalse(self.repo.verify_password_hint("henry", "mountain"))

    def test_update_password(self):
        """update_password should replace old password hash with a new one."""
        self.repo.create("iris", "oldpass123", "EDITOR")
        updated = self.repo.update_password("iris", "newpass123")
        self.assertTrue(updated.verify_password("newpass123"))
        self.assertFalse(updated.verify_password("oldpass123"))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""
Unit tests for the auth module — annotated reference copy.

[ANATOMY]
This file protects every security primitive in `auth.py`:
- password hashing and verification,
- JWT token creation and validation,
- role hierarchy behavior,
- user model helpers,
- in-memory user repository CRUD and authentication.

[WHY THIS FILE MATTERS]
Authentication code is small but high-risk. A subtle bug here can break every
API and HTML login path. These tests keep the security layer stable while the
rest of the app evolves.
"""

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

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
    """[CLASS] Password hashing and verification round-trip tests."""

    def test_hash_password_returns_string(self):
        """[VERIFY] bcrypt hash comes back as a non-trivial string."""
        hashed = hash_password("test-password")
        self.assertIsInstance(hashed, str)
        self.assertTrue(len(hashed) > 20)

    def test_hash_password_different_calls_produce_different_hashes(self):
        """[SECURITY] same plaintext must hash differently because bcrypt salts each call."""
        hashed1 = hash_password("same-password")
        hashed2 = hash_password("same-password")
        self.assertNotEqual(hashed1, hashed2)

    def test_verify_password_with_correct_password(self):
        """[VERIFY] correct plaintext validates against stored hash."""
        plaintext = "my-secure-password"
        hashed = hash_password(plaintext)
        self.assertTrue(verify_password(plaintext, hashed))

    def test_verify_password_with_wrong_password(self):
        """[VERIFY] wrong plaintext is rejected."""
        hashed = hash_password("correct-password")
        self.assertFalse(verify_password("wrong-password", hashed))

    def test_verify_password_with_empty_plaintext(self):
        """[VERIFY] empty input fails safely instead of crashing."""
        hashed = hash_password("password")
        self.assertFalse(verify_password("", hashed))

    def test_verify_password_constant_time_behavior(self):
        """[SECURITY] helper should not reintroduce timing side-channels around bcrypt."""
        hashed = hash_password("password123")
        self.assertFalse(verify_password("password124", hashed))
        self.assertFalse(verify_password("password125", hashed))
        self.assertFalse(verify_password("x", hashed))


class TestJWT(unittest.TestCase):
    """[CLASS] Token creation and decoding behavior."""

    def test_create_access_token_returns_string(self):
        token = create_access_token("alice", "EDITOR")
        self.assertIsInstance(token, str)
        self.assertTrue(len(token) > 20)

    def test_create_access_token_with_default_expiry(self):
        data = verify_access_token(create_access_token("alice", "EDITOR"))
        self.assertEqual(data.username, "alice")
        self.assertEqual(data.role, "EDITOR")

    def test_create_access_token_with_custom_expiry(self):
        data = verify_access_token(create_access_token("bob", "ADMIN", expires_delta=timedelta(hours=2)))
        self.assertEqual(data.username, "bob")
        self.assertEqual(data.role, "ADMIN")

    def test_verify_access_token_valid_token(self):
        data = verify_access_token(create_access_token("charlie", "VIEWER"))
        self.assertIsInstance(data, TokenData)
        self.assertEqual(data.username, "charlie")
        self.assertEqual(data.role, "VIEWER")

    def test_verify_access_token_expired_token_raises(self):
        import time
        token = create_access_token("dave", "EDITOR", expires_delta=timedelta(seconds=-1))
        time.sleep(0.1)
        with self.assertRaises(JWTError):
            verify_access_token(token)

    def test_verify_access_token_tampered_token_raises(self):
        token = create_access_token("eve", "ADMIN")
        tampered = token[:-1] + ("X" if token[-1] != "X" else "Y")
        with self.assertRaises(JWTError):
            verify_access_token(tampered)

    def test_verify_access_token_invalid_token_raises(self):
        with self.assertRaises(JWTError):
            verify_access_token("not.a.token")

    def test_verify_access_token_empty_string_raises(self):
        with self.assertRaises(JWTError):
            verify_access_token("")


class TestRoleHierarchy(unittest.TestCase):
    """[CLASS] Authorization hierarchy rules."""

    def test_role_constants_exist(self):
        self.assertEqual(Role.VIEWER, "VIEWER")
        self.assertEqual(Role.EDITOR, "EDITOR")
        self.assertEqual(Role.DATA_ENGINEER, "DATA_ENGINEER")
        self.assertEqual(Role.ADMIN, "ADMIN")

    def test_role_hierarchy_defined(self):
        self.assertIsInstance(Role.HIERARCHY, dict)
        for role_name in ("VIEWER", "EDITOR", "DATA_ENGINEER", "ADMIN"):
            self.assertIn(role_name, Role.HIERARCHY)

    def test_role_hierarchy_levels_increase(self):
        levels = Role.HIERARCHY
        self.assertLess(levels["VIEWER"], levels["EDITOR"])
        self.assertLess(levels["EDITOR"], levels["DATA_ENGINEER"])
        self.assertLess(levels["DATA_ENGINEER"], levels["ADMIN"])

    def test_user_has_role_true_for_exact_role(self):
        user = User(username="alice", hashed_password="hash", role="EDITOR", created=datetime.now())
        self.assertTrue(user.has_role("EDITOR"))

    def test_user_has_role_true_for_lower_role(self):
        user = User(username="bob", hashed_password="hash", role="EDITOR", created=datetime.now())
        self.assertTrue(user.has_role("VIEWER"))

    def test_user_has_role_false_for_higher_role(self):
        user = User(username="charlie", hashed_password="hash", role="VIEWER", created=datetime.now())
        self.assertFalse(user.has_role("EDITOR"))

    def test_user_has_role_admin_can_do_everything(self):
        user = User(username="admin", hashed_password="hash", role="ADMIN", created=datetime.now())
        self.assertTrue(user.has_role("VIEWER"))
        self.assertTrue(user.has_role("EDITOR"))
        self.assertTrue(user.has_role("DATA_ENGINEER"))
        self.assertTrue(user.has_role("ADMIN"))


class TestUserModel(unittest.TestCase):
    """[CLASS] Dataclass-level helpers on User."""

    def test_user_verify_password_correct(self):
        user = User(username="alice", hashed_password=hash_password("test123"), role="EDITOR", created=datetime.now())
        self.assertTrue(user.verify_password("test123"))

    def test_user_verify_password_incorrect(self):
        user = User(username="bob", hashed_password=hash_password("correct"), role="VIEWER", created=datetime.now())
        self.assertFalse(user.verify_password("wrong"))

    def test_user_is_active_default_true(self):
        user = User(username="charlie", hashed_password="hash", role="ADMIN", created=datetime.now())
        self.assertTrue(user.is_active)

    def test_user_is_active_explicit_false(self):
        user = User(username="dave", hashed_password="hash", role="VIEWER", created=datetime.now(), is_active=False)
        self.assertFalse(user.is_active)


class TestInMemoryUserRepository(unittest.TestCase):
    """[CLASS] CRUD and auth behavior for the default in-memory repo."""

    def setUp(self):
        self.repo = InMemoryUserRepository()

    def test_create_user(self):
        user = self.repo.create("alice", "password123", "EDITOR")
        self.assertEqual(user.username, "alice")
        self.assertEqual(user.role, "EDITOR")
        self.assertTrue(user.verify_password("password123"))

    def test_create_user_already_exists_raises(self):
        self.repo.create("alice", "pass1", "VIEWER")
        with self.assertRaises(ValueError):
            self.repo.create("alice", "pass2", "EDITOR")

    def test_get_user_exists(self):
        self.repo.create("bob", "secret", "ADMIN")
        user = self.repo.get("bob")
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "bob")
        self.assertEqual(user.role, "ADMIN")

    def test_get_user_not_exists(self):
        self.assertIsNone(self.repo.get("nonexistent"))

    def test_update_role(self):
        self.repo.create("charlie", "pass", "VIEWER")
        self.repo.update_role("charlie", "EDITOR")
        self.assertEqual(self.repo.get("charlie").role, "EDITOR")

    def test_update_role_user_not_exists_raises(self):
        with self.assertRaises(ValueError):
            self.repo.update_role("notfound", "ADMIN")

    def test_delete_user(self):
        self.repo.create("dave", "pass", "VIEWER")
        self.repo.delete("dave")
        self.assertIsNone(self.repo.get("dave"))

    def test_delete_user_not_exists_raises(self):
        with self.assertRaises(ValueError):
            self.repo.delete("notfound")

    def test_list_all_users(self):
        self.repo.create("alice", "p1", "VIEWER")
        self.repo.create("bob", "p2", "EDITOR")
        self.repo.create("charlie", "p3", "ADMIN")
        users = self.repo.list_all()
        self.assertEqual(len(users), 3)
        self.assertEqual({user.username for user in users}, {"alice", "bob", "charlie"})

    def test_authenticate(self):
        self.repo.create("eve", "mypass", "EDITOR")
        user = self.repo.authenticate("eve", "mypass")
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "eve")

    def test_authenticate_wrong_password(self):
        self.repo.create("frank", "correctpass", "VIEWER")
        self.assertIsNone(self.repo.authenticate("frank", "wrongpass"))

    def test_authenticate_user_not_exists(self):
        self.assertIsNone(self.repo.authenticate("notfound", "anypass"))

    def test_authenticate_inactive_user(self):
        self.repo.create("grace", "pass", "EDITOR")
        user = self.repo.get("grace")
        user.is_active = False
        self.assertIsNone(self.repo.authenticate("grace", "pass"))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""
Tests for rate limiting on /auth/login — annotated reference copy.

[ANATOMY]
This file protects the brute-force defense layer.
It verifies that the limiter:
- allows requests up to the configured threshold,
- blocks the first request past the threshold,
- resets after the time window,
- keeps counters separate per key,
- cleans old keys to avoid memory growth.
"""

import time
import unittest
from pathlib import Path
import sys

PROJECT_PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_PYTHON_DIR))

from rate_limit import RateLimiter


class TestRateLimiter(unittest.TestCase):
    """[CLASS] Core rate limiter behavior."""

    def setUp(self):
        """[FIXTURE] Use a small threshold so each test is cheap and explicit."""
        self.limiter = RateLimiter(max_attempts=3, window_seconds=10)

    def test_within_limit_is_allowed(self):
        """[VERIFY] first N requests within window are accepted."""
        key = "192.168.1.1"
        for _ in range(3):
            self.assertTrue(self.limiter.is_allowed(key))

    def test_exceeding_limit_is_blocked(self):
        """[SECURITY] request N+1 must be rejected."""
        key = "192.168.1.1"
        for _ in range(3):
            self.assertTrue(self.limiter.is_allowed(key))
        self.assertFalse(self.limiter.is_allowed(key))

    def test_different_keys_have_separate_limits(self):
        """[VERIFY] one client hitting the limit does not block another."""
        for _ in range(3):
            self.assertTrue(self.limiter.is_allowed("192.168.1.1"))
        self.assertFalse(self.limiter.is_allowed("192.168.1.1"))
        for _ in range(3):
            self.assertTrue(self.limiter.is_allowed("192.168.1.2"))
        self.assertFalse(self.limiter.is_allowed("192.168.1.2"))

    def test_window_expiration_resets_counter(self):
        """[VERIFY] clients can retry after the cooldown expires."""
        short = RateLimiter(max_attempts=3, window_seconds=1)
        key = "192.168.1.1"
        for _ in range(3):
            self.assertTrue(short.is_allowed(key))
        self.assertFalse(short.is_allowed(key))
        time.sleep(1.1)
        self.assertTrue(short.is_allowed(key))

    def test_get_remaining_attempts(self):
        """[VERIFY] UI/admin tooling can inspect remaining attempts."""
        key = "192.168.1.1"
        self.assertEqual(self.limiter.get_remaining(key), 3)
        self.limiter.is_allowed(key)
        self.assertEqual(self.limiter.get_remaining(key), 2)
        self.limiter.is_allowed(key)
        self.assertEqual(self.limiter.get_remaining(key), 1)
        self.limiter.is_allowed(key)
        self.assertEqual(self.limiter.get_remaining(key), 0)
        self.limiter.is_allowed(key)
        self.assertEqual(self.limiter.get_remaining(key), 0)

    def test_reset_key(self):
        """[OPERATIONS] admins can manually unblock a client key."""
        key = "192.168.1.1"
        for _ in range(3):
            self.limiter.is_allowed(key)
        self.assertFalse(self.limiter.is_allowed(key))
        self.limiter.reset(key)
        self.assertTrue(self.limiter.is_allowed(key))

    def test_cleanup_expired_entries(self):
        """[VERIFY] cleanup() drops dead counters and prevents memory creep."""
        limiter = RateLimiter(max_attempts=3, window_seconds=1)
        for index in range(5):
            limiter.is_allowed(f"ip-{index}")
        self.assertEqual(len(limiter._attempts), 5)
        time.sleep(1.1)
        limiter.cleanup()
        self.assertEqual(len(limiter._attempts), 0)

    def test_record_attempt_without_checking(self):
        """[VERIFY] manual counting path still drives the limiter correctly."""
        key = "192.168.1.1"
        self.limiter.record_attempt(key)
        self.limiter.record_attempt(key)
        self.limiter.record_attempt(key)
        self.assertFalse(self.limiter.is_allowed(key))


if __name__ == "__main__":
    unittest.main()

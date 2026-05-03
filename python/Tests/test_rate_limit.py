#!/usr/bin/env python3
"""
Tests for rate limiting on /auth/login endpoint.
Prevents brute-force attacks by limiting login attempts per IP/user.
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
	"""Test rate limiting functionality."""

	def setUp(self):
		"""Create a fresh rate limiter for each test."""
		self.limiter = RateLimiter(max_attempts=3, window_seconds=10)

	def test_within_limit_is_allowed(self):
		"""Requests within the limit are allowed."""
		key = "192.168.1.1"
		for i in range(3):
			self.assertTrue(self.limiter.is_allowed(key))

	def test_exceeding_limit_is_blocked(self):
		"""4th request in the window is blocked."""
		key = "192.168.1.1"
		for i in range(3):
			self.assertTrue(self.limiter.is_allowed(key))
		# 4th request should be blocked
		self.assertFalse(self.limiter.is_allowed(key))

	def test_different_keys_have_separate_limits(self):
		"""Different IPs/users have independent limits."""
		self.assertTrue(self.limiter.is_allowed("192.168.1.1"))
		self.assertTrue(self.limiter.is_allowed("192.168.1.1"))
		self.assertTrue(self.limiter.is_allowed("192.168.1.1"))
		# 192.168.1.1 is now blocked
		self.assertFalse(self.limiter.is_allowed("192.168.1.1"))
		
		# But 192.168.1.2 is still within limit
		self.assertTrue(self.limiter.is_allowed("192.168.1.2"))
		self.assertTrue(self.limiter.is_allowed("192.168.1.2"))
		self.assertTrue(self.limiter.is_allowed("192.168.1.2"))
		self.assertFalse(self.limiter.is_allowed("192.168.1.2"))

	def test_window_expiration_resets_counter(self):
		"""After window expires, counter resets and requests are allowed again."""
		key = "192.168.1.1"
		
		# Exhaust the limit
		for i in range(3):
			self.assertTrue(self.limiter.is_allowed(key))
		self.assertFalse(self.limiter.is_allowed(key))
		
		# Wait for window to expire (use short 1-second window for testing)
		limiter_short = RateLimiter(max_attempts=3, window_seconds=1)
		
		# Exhaust the limit
		for i in range(3):
			self.assertTrue(limiter_short.is_allowed(key))
		self.assertFalse(limiter_short.is_allowed(key))
		
		# Wait for window to expire
		time.sleep(1.1)
		
		# Now requests should be allowed again
		self.assertTrue(limiter_short.is_allowed(key))

	def test_get_remaining_attempts(self):
		"""Track remaining attempts before rate limit."""
		key = "192.168.1.1"
		
		self.assertEqual(self.limiter.get_remaining(key), 3)
		self.limiter.is_allowed(key)
		self.assertEqual(self.limiter.get_remaining(key), 2)
		self.limiter.is_allowed(key)
		self.assertEqual(self.limiter.get_remaining(key), 1)
		self.limiter.is_allowed(key)
		self.assertEqual(self.limiter.get_remaining(key), 0)
		self.limiter.is_allowed(key)  # Blocked, but counter still 0
		self.assertEqual(self.limiter.get_remaining(key), 0)

	def test_reset_key(self):
		"""Manually reset the counter for a key."""
		key = "192.168.1.1"
		
		# Exhaust the limit
		for i in range(3):
			self.limiter.is_allowed(key)
		self.assertFalse(self.limiter.is_allowed(key))
		
		# Reset the key
		self.limiter.reset(key)
		
		# Now requests are allowed again
		self.assertTrue(self.limiter.is_allowed(key))

	def test_cleanup_expired_entries(self):
		"""Expired entries are cleaned up to prevent memory leak."""
		limiter = RateLimiter(max_attempts=3, window_seconds=1)
		
		# Create some entries
		for i in range(5):
			limiter.is_allowed(f"ip-{i}")
		
		# Count entries
		initial_count = len(limiter._attempts)
		self.assertEqual(initial_count, 5)
		
		# Wait for window to expire
		time.sleep(1.1)
		
		# Cleanup should remove expired entries
		limiter.cleanup()
		
		# Should have fewer entries (all 5 should be expired and removed)
		cleaned_count = len(limiter._attempts)
		self.assertEqual(cleaned_count, 0)

	def test_record_attempt_without_checking(self):
		"""Record an attempt manually (useful for audit integration)."""
		key = "192.168.1.1"
		
		# Manually record attempts
		self.limiter.record_attempt(key)
		self.limiter.record_attempt(key)
		self.limiter.record_attempt(key)
		
		# Now check — should be at limit
		self.assertFalse(self.limiter.is_allowed(key))


if __name__ == "__main__":
	unittest.main()

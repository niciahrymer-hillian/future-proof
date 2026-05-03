#!/usr/bin/env python3
"""
Rate limiting module.
Prevents brute-force attacks by limiting login attempts per IP/identifier.

[ANATOMY]
- RateLimiter: Tracks request count per key (IP address, username, etc.) within a time window
"""

from time import time
from typing import Dict, Tuple


class RateLimiter:
    """
    [ANATOMY]
    Tracks request count per key (IP, username, etc.) within a sliding time window.
    
    [FIELD] _attempts: Dict[key] → (count, first_attempt_time)
    [FIELD] max_attempts: Maximum requests allowed per window
    [FIELD] window_seconds: Duration of the rate limit window (sliding)
    
    [WHY]
    - Prevents brute-force login attacks by rejecting excessive requests
    - Per-key tracking: separate limits for each IP/user (fair to other users)
    - Sliding window: resets automatically after window_seconds (no manual cleanup needed)
    - Memory efficient: old entries are never accessed after window expires
    
    [EFFECT]
    - /auth/login endpoint checks is_allowed(client_ip) before processing
    - Failed logins count as attempts (brute-force protection)
    - Successful logins also count (rate limit all traffic, not just failures)
    - After window expires, counter resets automatically
    
    [SECURITY NOTE]
    - Rate limit by IP address (protect against distributed attacks)
    - Also consider rate limiting by username (protect specific accounts)
    - Log rate limit violations for security monitoring
    
    [PATTERN]
    Typically used as middleware or dependency in FastAPI:
    ```
    limiter = RateLimiter(max_attempts=5, window_seconds=300)  # 5 attempts per 5 minutes
    
    @app.post("/auth/login")
    def login(request: LoginRequest, audit: AuditLog = ...):
        client_ip = request.client.host
        if not limiter.is_allowed(client_ip):
            audit.record(request.username, "LOGIN_RATE_LIMITED", "auth", {})
            raise HTTPException(429, "Too many login attempts. Try again later.")
        # ... proceed with login
    ```
    """

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300):
        """
        [EFFECT]
        Initialize rate limiter with max attempts per window.
        
        [PARAMETER] max_attempts: How many requests allowed per window (default 5)
        [PARAMETER] window_seconds: Duration of the time window in seconds (default 300 = 5 min)
        """
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        # Dict[key] → (count, first_attempt_timestamp)
        self._attempts: Dict[str, Tuple[int, float]] = {}

    def is_allowed(self, key: str) -> bool:
        """
        [EFFECT]
        Check if a request from this key is allowed.
        If allowed, increments the counter.
        If not allowed, does NOT increment (attacker can't spam to discover limits).
        Returns True if within limit, False if exceeded.
        
        [PARAMETER] key: Unique identifier (IP address, username, etc.)
        [RETURN] bool: True if request should be allowed, False if rate limited
        """
        current_time = time()
        
        # If key not in attempts, it's a new request — allow it
        if key not in self._attempts:
            self._attempts[key] = (1, current_time)
            return True
        
        count, first_attempt_time = self._attempts[key]
        time_since_first = current_time - first_attempt_time
        
        # If window has expired, reset the counter
        if time_since_first > self.window_seconds:
            self._attempts[key] = (1, current_time)
            return True
        
        # Within the window — check if over limit
        if count < self.max_attempts:
            # Still within limit — increment and allow
            self._attempts[key] = (count + 1, first_attempt_time)
            return True
        
        # Over limit — reject (don't increment)
        return False

    def get_remaining(self, key: str) -> int:
        """
        [EFFECT]
        Return remaining attempts before rate limit.
        Returns max_attempts if key has no record.
        
        [PARAMETER] key: Unique identifier
        [RETURN] int: Number of attempts remaining (0 if limit reached)
        """
        if key not in self._attempts:
            return self.max_attempts
        
        count, first_attempt_time = self._attempts[key]
        time_since_first = time() - first_attempt_time
        
        # If window has expired, counter has reset
        if time_since_first > self.window_seconds:
            return self.max_attempts
        
        return max(0, self.max_attempts - count)

    def reset(self, key: str) -> None:
        """
        [EFFECT]
        Manually reset the counter for a key.
        Used by admins to unblock accounts after investigation.
        
        [USAGE]
        # Admin manually unlocks a user
        limiter.reset("192.168.1.1")
        """
        if key in self._attempts:
            del self._attempts[key]

    def record_attempt(self, key: str) -> bool:
        """
        [EFFECT]
        Record an attempt without checking the limit.
        Useful for manual tracking or audit integration.
        Returns True if still within limit after recording, False if now over limit.
        
        [USAGE]
        # Audit log records a failed login, and we manually track it
        limiter.record_attempt(client_ip)
        """
        current_time = time()
        
        if key not in self._attempts:
            self._attempts[key] = (1, current_time)
            return True
        
        count, first_attempt_time = self._attempts[key]
        time_since_first = current_time - first_attempt_time
        
        # If window has expired, reset
        if time_since_first > self.window_seconds:
            self._attempts[key] = (1, current_time)
            return True
        
        # Increment counter
        self._attempts[key] = (count + 1, first_attempt_time)
        return count + 1 <= self.max_attempts

    def cleanup(self) -> None:
        """
        [EFFECT]
        Remove expired entries from the tracking dict.
        Prevents memory leak from accumulating old keys.
        
        [WHY MANUAL CLEANUP]
        Sliding window means entries expire on their own.
        Cleanup is optional — for production, run periodically in background.
        
        [USAGE]
        # In a background task or periodically during maintenance:
        limiter.cleanup()
        """
        current_time = time()
        keys_to_remove = []
        
        for key, (count, first_attempt_time) in self._attempts.items():
            if current_time - first_attempt_time > self.window_seconds:
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self._attempts[key]

#!/usr/bin/env python3
"""
Rate limiting module — Prevents brute-force attacks by limiting login attempts per IP/identifier.

[ANATOMY]
- RateLimiter: Tracks request count per key (IP address, username, etc.) within a time window
  - Uses sliding window approach: each key has (attempt_count, first_attempt_timestamp)
  - Automatically resets when window expires
  - Separate limits for each key (fair to legitimate users)
"""

from time import time
from typing import Dict, Tuple


class RateLimiter:
    """
    [ANATOMY]
    Tracks request count per key (IP, username, etc.) within a sliding time window.
    
    [FIELD] _attempts: Dict[key] → (count, first_attempt_time)
           Stores the number of attempts and when the window started for each key.
    [FIELD] max_attempts: Maximum requests allowed per window (e.g., 5)
    [FIELD] window_seconds: Duration of the rate limit window in seconds (e.g., 300 = 5 min)
    
    [WHY]
    - Prevents brute-force login attacks by rejecting excessive requests from same IP
    - Per-key tracking: separate limits for each IP/user (fair to other legitimate users)
    - Sliding window: resets automatically after window_seconds (no manual cleanup)
    - Memory efficient: old entries are naturally expired and never accessed again
    - Simple O(1) operations: is_allowed(), reset() are constant time
    
    [EFFECT]
    - /auth/login endpoint checks is_allowed(client_ip) before processing
    - After limit exceeded, endpoint returns 429 Too Many Requests
    - Failed login attempts count the same as successful (prevent user enumeration)
    - After window expires, counter resets automatically
    - Admin can manually reset a key with reset(key) after investigation
    
    [SECURITY NOTE]
    - Rate limit by IP address to protect against distributed attacks
    - Also consider rate limiting by username to protect specific accounts from enumeration
    - Log rate limit violations (audit.record()) for security monitoring
    - Return generic 429 error (don't reveal when user will be unblocked)
    
    [PATTERN]
    Typical FastAPI integration:
    ```
    limiter = RateLimiter(max_attempts=5, window_seconds=300)  # 5 attempts per 5 minutes
    
    @app.post("/auth/login")
    def login(request: Request, login_data: LoginRequest, limiter: RateLimiter = Depends(get_rate_limiter)):
        client_ip = request.client.host
        if not limiter.is_allowed(client_ip):
            audit.record(login_data.username, "LOGIN_RATE_LIMITED", "auth", {})
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
        
        [USAGE]
        limiter = RateLimiter(max_attempts=5, window_seconds=300)  # Typical: 5 attempts per 5 min
        limiter = RateLimiter(max_attempts=10, window_seconds=60)  # Strict: 10 per minute
        limiter = RateLimiter(max_attempts=100, window_seconds=3600)  # Lenient: 100 per hour
        """
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        # Dict[key] → (count, first_attempt_timestamp)
        # Stores (attempt_count, time_of_first_attempt) for each key
        self._attempts: Dict[str, Tuple[int, float]] = {}

    def is_allowed(self, key: str) -> bool:
        """
        [EFFECT]
        Check if a request from this key is allowed.
        If allowed, increments the counter and returns True.
        If not allowed, does NOT increment and returns False (attacker can't spam to discover exact limits).
        
        [LOGIC]
        1. If key not seen before: record first attempt time, allow request (return True)
        2. If window expired: reset counter, allow request (return True)
        3. If within limit: increment counter, allow request (return True)
        4. If over limit: reject request (return False), do NOT increment (stop feedback to attacker)
        
        [PARAMETER] key: Unique identifier (e.g., client IP "192.168.1.1", username "alice", or "testclient" for tests)
        [RETURN] bool: True if request should be allowed, False if rate limited
        
        [USAGE]
        if not limiter.is_allowed("192.168.1.1"):
            raise HTTPException(429, "Too many attempts")
        """
        current_time = time()
        
        # [CASE 1] Key not in attempts — first request from this key
        if key not in self._attempts:
            self._attempts[key] = (1, current_time)
            return True
        
        count, first_attempt_time = self._attempts[key]
        time_since_first = current_time - first_attempt_time
        
        # [CASE 2] Window has expired — reset the counter as if this is the first request
        if time_since_first > self.window_seconds:
            self._attempts[key] = (1, current_time)
            return True
        
        # [CASE 3] Within the window and still under limit — increment and allow
        if count < self.max_attempts:
            self._attempts[key] = (count + 1, first_attempt_time)
            return True
        
        # [CASE 4] Over limit — reject (don't increment, don't update timestamp)
        return False

    def get_remaining(self, key: str) -> int:
        """
        [EFFECT]
        Return remaining attempts before rate limit is hit.
        Returns max_attempts if key has no record.
        
        [PARAMETER] key: Unique identifier
        [RETURN] int: Number of attempts remaining (0 if limit reached, max_attempts if no record)
        
        [USAGE]
        remaining = limiter.get_remaining("192.168.1.1")
        if remaining < 2:
            # Warn user: "X attempts remaining"
            pass
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
        Used by admins to unblock accounts after security investigation.
        
        [USAGE]
        # Admin manually unlocks a user after verifying legitimate access:
        limiter.reset("192.168.1.1")
        
        [WHY NEEDED]
        If a legitimate user accidentally mistyped password multiple times, they get locked out.
        Admin can unblock them immediately instead of waiting for window to expire.
        """
        if key in self._attempts:
            del self._attempts[key]

    def record_attempt(self, key: str) -> bool:
        """
        [EFFECT]
        Record an attempt without checking the limit first.
        Useful for manual tracking or audit integration (e.g., record failed logins before rate check).
        Returns True if still within limit after recording, False if now over limit.
        
        [PARAMETER] key: Unique identifier
        [RETURN] bool: True if count <= max_attempts after recording, False if now over limit
        
        [USAGE]
        # Audit log records a failed login, and we manually track the attempt:
        limiter.record_attempt(client_ip)
        audit.record(username, "LOGIN_FAILED", "auth", {})
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
        Prevents memory leak from accumulating old keys that will never be accessed again.
        
        [WHY MANUAL CLEANUP]
        Sliding window means entries expire on their own naturally.
        But the dict entries persist in memory forever unless manually cleaned.
        For production, run cleanup() periodically in a background task.
        
        [USAGE]
        # In a periodic maintenance task (e.g., every 10 minutes):
        limiter.cleanup()
        
        [COMPLEXITY]
        O(n) where n = number of unique keys. Only run when dict is large.
        For small number of IPs (<1000), cleanup is negligible.
        For large deployments, consider using Redis or external rate limiter.
        """
        current_time = time()
        keys_to_remove = []
        
        for key, (count, first_attempt_time) in self._attempts.items():
            if current_time - first_attempt_time > self.window_seconds:
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self._attempts[key]

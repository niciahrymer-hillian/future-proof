#!/usr/bin/env python3
"""
Audit logging module — Records who did what, when, to which resources.

[ANATOMY]
- AuditEvent: Immutable data class for a single audit log entry (user, action, resource, details, timestamp)
- AuditLog: Append-only audit log with in-memory storage and optional file persistence (JSONL format)
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
import json


@dataclass
class AuditEvent:
    """
    [ANATOMY]
    Immutable audit log entry recording a single action.
    
    [FIELD] user: The username who performed the action.
    [FIELD] action: The type of action (e.g., "NOTE_CREATED", "LOGIN", "ROLE_CHANGED", "USER_DEACTIVATED").
    [FIELD] resource: The resource affected (e.g., "note-001", "auth", "user:alice").
    [FIELD] details: Dict with extra context — e.g., {"title": "My Note", "role": "ADMIN", "reason": "invalid_credentials"}.
    [FIELD] timestamp: When the event occurred (auto-set to now at event creation time).
    
    [WHY]
    - Immutable (@dataclass): once created, audit events are never modified — ensures history integrity.
    - Timestamp auto-set: each event captures the exact moment it was recorded, no guessing.
    - Details dict: flexible schema allows logging different info per action (title for notes, role for users, etc.)
    """
    user: str
    action: str
    resource: str
    details: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """
        [EFFECT]
        Convert event to dict for JSON serialization.
        Timestamp is ISO-formatted for storage and interoperability.
        Returns a dict suitable for json.dumps() or database insertion.
        """
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "AuditEvent":
        """
        [EFFECT]
        Reconstruct event from dict (e.g., loaded from JSON).
        Parses ISO timestamp string back to Python datetime object.
        """
        data_copy = data.copy()
        data_copy["timestamp"] = datetime.fromisoformat(data_copy["timestamp"])
        return AuditEvent(**data_copy)


class AuditLog:
    """
    [ANATOMY]
    Append-only audit log with in-memory storage and optional JSONL persistence.
    Public methods:
    - record(user, action, resource, details) → add one event
    - get_all() → all events in order
    - get_by_user(user) → filter by username
    - get_by_action(action) → filter by action type
    - get_by_resource(resource) → filter by resource
    - count() → total event count
    - clear() → reset in-memory log (testing only)
    - save_to_file(path) → write all events to JSONL file
    - load_from_file(path) → read events from JSONL file
    - append_to_file(path) → append events to JSONL file
    
    [WHY]
    - Append-only: events are never modified, only added — prevents tampering with history
    - Immutable records: AuditEvent objects are immutable (@dataclass)
    - Queryable: filter by user/action/resource for compliance, investigation, audits
    - Persistent: can save/load from JSONL for long-term retention and analysis
    - O(n) queries: acceptable for audit logs (not a high-throughput feature)
    
    [EFFECT]
    - All note operations (create, update, delete) are logged with who/what/when
    - All user management (create, role change, deactivate) is logged with admin identity
    - All logins (success and failure) are logged with reason
    - Audit trail is queryable by user (e.g., "what did alice do?"), action (e.g., "all logins"), or resource (e.g., "all changes to note-001")
    - For compliance: can answer "who changed role X on date Y?" or "what happened to user Z?"
    """

    def __init__(self):
        """
        [EFFECT]
        Initialize empty append-only log.
        _events list will only grow (never shrink except via clear() for testing).
        """
        self._events: List[AuditEvent] = []

    def record(
        self,
        user: str,
        action: str,
        resource: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """
        [EFFECT]
        Record a single audit event and append to the log.
        Returns the event (caller may use for testing or further processing).
        
        [USAGE]
        audit_log.record("alice", "NOTE_CREATED", "note-001", {"title": "My Note"})
        audit_log.record("admin", "ROLE_CHANGED", "user:bob", {"new_role": "ADMIN"})
        audit_log.record("alice", "LOGIN_FAILED", "auth", {"reason": "invalid_credentials"})
        """
        if details is None:
            details = {}
        event = AuditEvent(user=user, action=action, resource=resource, details=details)
        self._events.append(event)
        return event

    def get_all(self) -> List[AuditEvent]:
        """
        [EFFECT]
        Return all events in chronological order (oldest first).
        Caller gets a copy (list()) so modifications don't affect the log.
        """
        return list(self._events)

    def get_by_user(self, user: str) -> List[AuditEvent]:
        """
        [EFFECT]
        Return all events from a specific user.
        Useful for: "what did alice do?" or "show all actions by admin".
        """
        return [e for e in self._events if e.user == user]

    def get_by_action(self, action: str) -> List[AuditEvent]:
        """
        [EFFECT]
        Return all events of a specific action type.
        Useful for: "show all login attempts" or "all note creations".
        """
        return [e for e in self._events if e.action == action]

    def get_by_resource(self, resource: str) -> List[AuditEvent]:
        """
        [EFFECT]
        Return all events affecting a specific resource.
        Useful for: "what happened to note-001?" or "all changes to user:bob".
        """
        return [e for e in self._events if e.resource == resource]

    def count(self) -> int:
        """
        [EFFECT]
        Return total number of events logged.
        O(1) operation.
        """
        return len(self._events)

    def clear(self) -> None:
        """
        [EFFECT]
        Clear all events from the in-memory log.
        Used only in tests to reset state between test cases.
        
        [WHY TESTED]
        Tests depend on a clean slate; clear() allows each test to start fresh
        without creating a new AuditLog instance.
        """
        self._events.clear()

    def save_to_file(self, file_path: str) -> None:
        """
        [EFFECT]
        Write all events to a JSONL file (one JSON object per line).
        Each line is a complete AuditEvent in JSON format.
        Useful for:
        - Initial export or full backup of audit trail
        - Retention archive (append-only JSONL is tamper-evident)
        
        [USAGE]
        audit_log.save_to_file("/var/log/notes-app-audit.jsonl")
        """
        with open(file_path, 'w') as f:
            for event in self._events:
                line = json.dumps(event.to_dict())
                f.write(line + '\n')

    def load_from_file(self, file_path: str) -> None:
        """
        [EFFECT]
        Load events from a JSONL file into the in-memory log.
        Clears existing events before loading (full replacement).
        If file does not exist, silently returns (no events loaded).
        
        [USAGE]
        audit_log.load_from_file("/var/log/notes-app-audit.jsonl")
        """
        self._events.clear()
        if not Path(file_path).exists():
            return
        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                event = AuditEvent.from_dict(data)
                self._events.append(event)

    def append_to_file(self, file_path: str) -> None:
        """
        [EFFECT]
        Append new events to a JSONL file.
        
        [WHY NAIVE]
        Current implementation rewrites the entire file (inefficient but safe).
        In production, track the index or timestamp of the last written event
        and only append new entries since then.
        
        [USAGE]
        # After recording some new events...
        audit_log.record(...)
        audit_log.record(...)
        # ...persist them:
        audit_log.append_to_file("/var/log/notes-app-audit.jsonl")
        """
        self.save_to_file(file_path)

#!/usr/bin/env python3
"""
Audit logging module.
Records who did what, when, to which resources.

[ANATOMY]
- AuditEvent: Immutable data class for a single audit log entry
- AuditLog: Append-only audit log with in-memory storage and optional file persistence
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
    
    [FIELD] user: The user who performed the action.
    [FIELD] action: The type of action (e.g., "NOTE_CREATED", "LOGIN", "ROLE_CHANGED").
    [FIELD] resource: The resource affected (e.g., "note-001", "auth", "user:alice").
    [FIELD] details: Dict with extra context (e.g., {"title": "My Note", "tags": ["urgent"]}).
    [FIELD] timestamp: When the event occurred (auto-set to now).
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
        Timestamp is ISO-formatted for storage.
        """
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "AuditEvent":
        """
        [EFFECT]
        Reconstruct event from dict (e.g., loaded from JSON).
        Parses ISO timestamp back to datetime.
        """
        data_copy = data.copy()
        data_copy["timestamp"] = datetime.fromisoformat(data_copy["timestamp"])
        return AuditEvent(**data_copy)


class AuditLog:
    """
    [ANATOMY]
    Append-only audit log with in-memory storage.
    
    [WHY]
    - Append-only: events are never modified, only added
    - Immutable: past events can't be tampered with (security baseline)
    - Queryable: filter by user/action/resource for compliance/investigation
    - Persistent: can save/load from JSONL for retention
    
    [EFFECT]
    - All note operations, user management, logins go through this log
    - Slow-path queries (filter ops) are O(n) — acceptable for audit logs
    - File format is JSONL (one event per line) for append-only durability
    """

    def __init__(self):
        """Initialize empty append-only log."""
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
        Record a single audit event.
        Returns the event (caller may use for testing).
        """
        if details is None:
            details = {}
        event = AuditEvent(user=user, action=action, resource=resource, details=details)
        self._events.append(event)
        return event

    def get_all(self) -> List[AuditEvent]:
        """[EFFECT] Return all events in chronological order."""
        return list(self._events)

    def get_by_user(self, user: str) -> List[AuditEvent]:
        """[EFFECT] Return all events from a specific user."""
        return [e for e in self._events if e.user == user]

    def get_by_action(self, action: str) -> List[AuditEvent]:
        """[EFFECT] Return all events of a specific action type."""
        return [e for e in self._events if e.action == action]

    def get_by_resource(self, resource: str) -> List[AuditEvent]:
        """[EFFECT] Return all events affecting a specific resource."""
        return [e for e in self._events if e.resource == resource]

    def count(self) -> int:
        """[EFFECT] Return total number of events logged."""
        return len(self._events)

    def clear(self) -> None:
        """
        [EFFECT]
        Clear all events from the in-memory log.
        Used in tests to reset state.
        """
        self._events.clear()

    def save_to_file(self, file_path: str) -> None:
        """
        [EFFECT]
        Write all events to a JSONL file (one JSON object per line).
        Useful for initial export or full backup.
        """
        with open(file_path, 'w') as f:
            for event in self._events:
                line = json.dumps(event.to_dict())
                f.write(line + '\n')

    def load_from_file(self, file_path: str) -> None:
        """
        [EFFECT]
        Load events from a JSONL file into the in-memory log.
        Clears existing events before loading.
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
        Append only the newest events to a JSONL file.
        Caller is responsible for tracking which events are new.
        For now, appends *all* events in the log (naive approach).
        
        [WHY]
        In production, you'd track index or timestamp of last written event.
        For this demo, we rewrite the full log (inefficient but safe).
        """
        self.save_to_file(file_path)

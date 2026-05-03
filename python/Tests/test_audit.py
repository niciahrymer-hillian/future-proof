#!/usr/bin/env python3
"""
Tests for audit logging module.
Verifies that audit events are recorded with user, action, resource, timestamp.
"""

import unittest
from datetime import datetime
from pathlib import Path
import tempfile
import json
import sys

PROJECT_PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_PYTHON_DIR) not in sys.path:
	sys.path.insert(0, str(PROJECT_PYTHON_DIR))

from audit import AuditLog, AuditEvent


class TestAuditEvent(unittest.TestCase):
    """Test AuditEvent model creation and validation."""

    def test_create_event_with_all_fields(self):
        """Create an event with user, action, resource, details."""
        event = AuditEvent(
            user="alice",
            action="NOTE_CREATED",
            resource="note-001",
            details={"title": "My Note"}
        )
        self.assertEqual(event.user, "alice")
        self.assertEqual(event.action, "NOTE_CREATED")
        self.assertEqual(event.resource, "note-001")
        self.assertEqual(event.details, {"title": "My Note"})
        self.assertIsInstance(event.timestamp, datetime)

    def test_event_timestamp_is_recent(self):
        """Timestamp should be close to now."""
        before = datetime.now()
        event = AuditEvent(user="bob", action="LOGIN", resource="auth", details={})
        after = datetime.now()
        self.assertGreaterEqual(event.timestamp, before)
        self.assertLessEqual(event.timestamp, after)

    def test_event_to_dict(self):
        """Convert event to dict for logging/serialization."""
        event = AuditEvent(
            user="charlie",
            action="ROLE_CHANGED",
            resource="user:bob",
            details={"new_role": "ADMIN"}
        )
        d = event.to_dict()
        self.assertEqual(d["user"], "charlie")
        self.assertEqual(d["action"], "ROLE_CHANGED")
        self.assertEqual(d["resource"], "user:bob")
        self.assertEqual(d["details"]["new_role"], "ADMIN")
        self.assertIn("timestamp", d)


class TestAuditLog(unittest.TestCase):
    """Test AuditLog append-only log functionality."""

    def setUp(self):
        """Create a fresh AuditLog for each test."""
        self.log = AuditLog()

    def test_log_event(self):
        """Record an event and verify it's stored."""
        self.log.record(
            user="alice",
            action="NOTE_CREATED",
            resource="note-001",
            details={"title": "Test"}
        )
        events = self.log.get_all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].user, "alice")
        self.assertEqual(events[0].action, "NOTE_CREATED")

    def test_log_multiple_events(self):
        """Record multiple events in sequence."""
        self.log.record("alice", "LOGIN", "auth", {})
        self.log.record("alice", "NOTE_CREATED", "note-001", {"title": "A"})
        self.log.record("bob", "LOGIN", "auth", {})
        events = self.log.get_all()
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0].user, "alice")
        self.assertEqual(events[1].user, "alice")
        self.assertEqual(events[2].user, "bob")

    def test_filter_by_user(self):
        """Query audit log filtered by username."""
        self.log.record("alice", "NOTE_CREATED", "note-001", {})
        self.log.record("bob", "NOTE_CREATED", "note-002", {})
        self.log.record("alice", "NOTE_UPDATED", "note-001", {})
        events = self.log.get_by_user("alice")
        self.assertEqual(len(events), 2)
        for event in events:
            self.assertEqual(event.user, "alice")

    def test_filter_by_action(self):
        """Query audit log filtered by action type."""
        self.log.record("alice", "LOGIN", "auth", {})
        self.log.record("alice", "NOTE_CREATED", "note-001", {})
        self.log.record("bob", "LOGIN", "auth", {})
        events = self.log.get_by_action("LOGIN")
        self.assertEqual(len(events), 2)
        for event in events:
            self.assertEqual(event.action, "LOGIN")

    def test_filter_by_resource(self):
        """Query audit log filtered by resource."""
        self.log.record("alice", "NOTE_CREATED", "note-001", {})
        self.log.record("alice", "NOTE_UPDATED", "note-001", {})
        self.log.record("bob", "NOTE_CREATED", "note-002", {})
        events = self.log.get_by_resource("note-001")
        self.assertEqual(len(events), 2)
        for event in events:
            self.assertEqual(event.resource, "note-001")

    def test_clear_log(self):
        """Clear all logged events."""
        self.log.record("alice", "NOTE_CREATED", "note-001", {})
        self.log.record("bob", "LOGIN", "auth", {})
        self.assertEqual(len(self.log.get_all()), 2)
        self.log.clear()
        self.assertEqual(len(self.log.get_all()), 0)

    def test_ordered_by_timestamp(self):
        """Events are returned in chronological order."""
        self.log.record("alice", "EVENT_1", "resource-1", {})
        self.log.record("bob", "EVENT_2", "resource-2", {})
        self.log.record("charlie", "EVENT_3", "resource-3", {})
        events = self.log.get_all()
        for i in range(len(events) - 1):
            self.assertLessEqual(events[i].timestamp, events[i + 1].timestamp)

    def test_get_count(self):
        """Get total count of events."""
        self.log.record("alice", "LOGIN", "auth", {})
        self.log.record("bob", "NOTE_CREATED", "note-001", {})
        self.assertEqual(self.log.count(), 2)


class TestAuditLogPersistence(unittest.TestCase):
    """Test optional file persistence for audit logs."""

    def setUp(self):
        """Create temp directory for log files."""
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = Path(self.temp_dir) / "audit.jsonl"

    def tearDown(self):
        """Clean up temp files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_to_file(self):
        """Save audit log to JSONL file."""
        log = AuditLog()
        log.record("alice", "NOTE_CREATED", "note-001", {"title": "Test"})
        log.record("bob", "NOTE_UPDATED", "note-001", {"title": "Updated"})
        log.save_to_file(str(self.log_file))
        self.assertTrue(self.log_file.exists())

    def test_load_from_file(self):
        """Load audit log from JSONL file."""
        # Write a log file manually
        with open(self.log_file, 'w') as f:
            f.write('{"user":"alice","action":"LOGIN","resource":"auth","timestamp":"2026-05-01T10:00:00","details":{}}\n')
            f.write('{"user":"bob","action":"NOTE_CREATED","resource":"note-001","timestamp":"2026-05-01T10:01:00","details":{}}\n')
        
        log = AuditLog()
        log.load_from_file(str(self.log_file))
        events = log.get_all()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].user, "alice")
        self.assertEqual(events[1].user, "bob")

    def test_append_to_file(self):
        """Append new events to existing file."""
        log = AuditLog()
        log.record("alice", "LOGIN", "auth", {})
        log.save_to_file(str(self.log_file))
        
        # Append more events
        log.record("bob", "NOTE_CREATED", "note-001", {})
        log.append_to_file(str(self.log_file))
        
        # Reload and verify both events are there
        log2 = AuditLog()
        log2.load_from_file(str(self.log_file))
        events = log2.get_all()
        self.assertEqual(len(events), 2)


if __name__ == "__main__":
    unittest.main()

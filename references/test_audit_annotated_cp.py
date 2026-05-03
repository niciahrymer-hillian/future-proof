#!/usr/bin/env python3
"""
Tests for audit logging module — annotated reference copy.

[ANATOMY]
This file protects the audit trail layer added in Option E.
It verifies three things:
1. `AuditEvent` builds a correct immutable record.
2. `AuditLog` stores/query/clears events correctly in memory.
3. JSONL persistence works for save/load/append flows.

[WHY THIS TEST FILE EXISTS]
Audit logging is only useful if it is trustworthy. These tests make sure
logged events keep the right user/action/resource/timestamp shape and that
persisted logs can be read back without losing meaning.
"""

import unittest
from datetime import datetime
from pathlib import Path
import tempfile
import sys

PROJECT_PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_PYTHON_DIR))

from audit import AuditLog, AuditEvent


class TestAuditEvent(unittest.TestCase):
    """[CLASS] Unit tests for one audit event record."""

    def test_create_event_with_all_fields(self):
        """[VERIFY] Event stores user, action, resource, details, timestamp."""
        event = AuditEvent(
            user="alice",
            action="NOTE_CREATED",
            resource="note-001",
            details={"title": "My Note"},
        )
        self.assertEqual(event.user, "alice")
        self.assertEqual(event.action, "NOTE_CREATED")
        self.assertEqual(event.resource, "note-001")
        self.assertEqual(event.details, {"title": "My Note"})
        self.assertIsInstance(event.timestamp, datetime)

    def test_event_timestamp_is_recent(self):
        """[VERIFY] default timestamp is generated at construction time."""
        before = datetime.now()
        event = AuditEvent(user="bob", action="LOGIN", resource="auth", details={})
        after = datetime.now()
        self.assertGreaterEqual(event.timestamp, before)
        self.assertLessEqual(event.timestamp, after)

    def test_event_to_dict(self):
        """[VERIFY] serialization converts timestamp to JSON-safe ISO string."""
        event = AuditEvent(
            user="charlie",
            action="ROLE_CHANGED",
            resource="user:bob",
            details={"new_role": "ADMIN"},
        )
        payload = event.to_dict()
        self.assertEqual(payload["user"], "charlie")
        self.assertEqual(payload["action"], "ROLE_CHANGED")
        self.assertEqual(payload["resource"], "user:bob")
        self.assertEqual(payload["details"]["new_role"], "ADMIN")
        self.assertIn("timestamp", payload)


class TestAuditLog(unittest.TestCase):
    """[CLASS] In-memory append-only audit log behavior."""

    def setUp(self):
        """[FIXTURE] Start each test with a clean log instance."""
        self.log = AuditLog()

    def test_log_event(self):
        """[VERIFY] record() appends an event."""
        self.log.record("alice", "NOTE_CREATED", "note-001", {"title": "Test"})
        events = self.log.get_all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].user, "alice")
        self.assertEqual(events[0].action, "NOTE_CREATED")

    def test_log_multiple_events(self):
        """[VERIFY] audit log preserves append order."""
        self.log.record("alice", "LOGIN", "auth", {})
        self.log.record("alice", "NOTE_CREATED", "note-001", {"title": "A"})
        self.log.record("bob", "LOGIN", "auth", {})
        events = self.log.get_all()
        self.assertEqual(len(events), 3)
        self.assertEqual([event.user for event in events], ["alice", "alice", "bob"])

    def test_filter_by_user(self):
        """[VERIFY] get_by_user() isolates one actor's history."""
        self.log.record("alice", "NOTE_CREATED", "note-001", {})
        self.log.record("bob", "NOTE_CREATED", "note-002", {})
        self.log.record("alice", "NOTE_UPDATED", "note-001", {})
        events = self.log.get_by_user("alice")
        self.assertEqual(len(events), 2)
        self.assertTrue(all(event.user == "alice" for event in events))

    def test_filter_by_action(self):
        """[VERIFY] get_by_action() groups related event types."""
        self.log.record("alice", "LOGIN", "auth", {})
        self.log.record("alice", "NOTE_CREATED", "note-001", {})
        self.log.record("bob", "LOGIN", "auth", {})
        events = self.log.get_by_action("LOGIN")
        self.assertEqual(len(events), 2)
        self.assertTrue(all(event.action == "LOGIN" for event in events))

    def test_filter_by_resource(self):
        """[VERIFY] get_by_resource() shows full history of one object."""
        self.log.record("alice", "NOTE_CREATED", "note-001", {})
        self.log.record("alice", "NOTE_UPDATED", "note-001", {})
        self.log.record("bob", "NOTE_CREATED", "note-002", {})
        events = self.log.get_by_resource("note-001")
        self.assertEqual(len(events), 2)
        self.assertTrue(all(event.resource == "note-001" for event in events))

    def test_clear_log(self):
        """[TEST ONLY] clear() resets shared state between tests."""
        self.log.record("alice", "NOTE_CREATED", "note-001", {})
        self.log.record("bob", "LOGIN", "auth", {})
        self.assertEqual(len(self.log.get_all()), 2)
        self.log.clear()
        self.assertEqual(len(self.log.get_all()), 0)

    def test_ordered_by_timestamp(self):
        """[VERIFY] append-only log returns events in chronological order."""
        self.log.record("alice", "EVENT_1", "resource-1", {})
        self.log.record("bob", "EVENT_2", "resource-2", {})
        self.log.record("charlie", "EVENT_3", "resource-3", {})
        events = self.log.get_all()
        for index in range(len(events) - 1):
            self.assertLessEqual(events[index].timestamp, events[index + 1].timestamp)

    def test_get_count(self):
        """[VERIFY] count() is a quick aggregate helper."""
        self.log.record("alice", "LOGIN", "auth", {})
        self.log.record("bob", "NOTE_CREATED", "note-001", {})
        self.assertEqual(self.log.count(), 2)


class TestAuditLogPersistence(unittest.TestCase):
    """[CLASS] JSONL persistence behavior for audit archives."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = Path(self.temp_dir) / "audit.jsonl"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_to_file(self):
        """[VERIFY] save_to_file() writes a persistent log file."""
        log = AuditLog()
        log.record("alice", "NOTE_CREATED", "note-001", {"title": "Test"})
        log.record("bob", "NOTE_UPDATED", "note-001", {"title": "Updated"})
        log.save_to_file(str(self.log_file))
        self.assertTrue(self.log_file.exists())

    def test_load_from_file(self):
        """[VERIFY] load_from_file() reconstructs prior history."""
        with open(self.log_file, "w", encoding="utf-8") as handle:
            handle.write('{"user":"alice","action":"LOGIN","resource":"auth","timestamp":"2026-05-01T10:00:00","details":{}}\n')
            handle.write('{"user":"bob","action":"NOTE_CREATED","resource":"note-001","timestamp":"2026-05-01T10:01:00","details":{}}\n')
        log = AuditLog()
        log.load_from_file(str(self.log_file))
        events = log.get_all()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].user, "alice")
        self.assertEqual(events[1].user, "bob")

    def test_append_to_file(self):
        """[VERIFY] append path preserves all events when file is rewritten."""
        log = AuditLog()
        log.record("alice", "LOGIN", "auth", {})
        log.save_to_file(str(self.log_file))
        log.record("bob", "NOTE_CREATED", "note-001", {})
        log.append_to_file(str(self.log_file))
        reloaded = AuditLog()
        reloaded.load_from_file(str(self.log_file))
        self.assertEqual(len(reloaded.get_all()), 2)


if __name__ == "__main__":
    unittest.main()

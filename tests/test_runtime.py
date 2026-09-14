from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cloud import relay, watchdog


class RelaySecurityTests(unittest.TestCase):
    def test_secret_requires_private_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secret"
            path.write_text("top-secret\n", encoding="utf-8")
            path.chmod(0o600)
            self.assertEqual(relay.read_secret(path), "top-secret")
            path.chmod(0o644)
            with self.assertRaises(RuntimeError):
                relay.read_secret(path)

    def test_sonar_normalization_rejects_unsafe_url(self) -> None:
        body = b'{"project":{"name":"demo","url":"file:///etc/passwd"},"qualityGate":{"status":"ERROR"}}'
        event_id, notification = relay.normalize_event("/webhooks/sonar", {}, body)
        self.assertEqual(len(event_id), 64)
        self.assertEqual(notification["source"], "sonar")
        self.assertEqual(notification["severity"], "warning")
        self.assertNotIn("url", notification)


class DurableQueueTests(unittest.TestCase):
    def test_duplicate_retry_permanent_failure_and_acknowledge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = relay.DurableQueue(Path(tmp) / "queue")
            notification = {"source": "sonar", "title": "gate", "text": "failed"}
            self.assertTrue(queue.enqueue("event-1", notification))
            self.assertFalse(queue.enqueue("event-1", notification))
            self.assertEqual(queue.depth(), 1)
            self.assertEqual(queue.pending_depth(), 1)

            due = queue.due(now=2**31)
            self.assertEqual(len(due), 1)
            path, item = due[0]
            queue.failed(path, item, error_code="HTTP_503")
            self.assertEqual(item.status, "retrying")
            self.assertEqual(item.attempts, 1)
            self.assertEqual(queue.pending_depth(), 1)

            queue.failed(path, item, error_code="HTTP_400", permanent=True)
            self.assertEqual(item.status, "permanent_failed")
            self.assertEqual(item.attempts, 2)
            self.assertEqual(queue.pending_depth(), 0)
            self.assertEqual(queue.permanent_failure_depth(), 1)

            queue.acknowledged(path)
            self.assertEqual(queue.depth(), 0)


class DeliveryLedgerTests(unittest.TestCase):
    def test_delivery_state_transitions_and_pruning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = relay.DeliveryLedger(Path(tmp) / "state" / "ledger.sqlite3")
            try:
                ledger.record_queued("event-1", "sonar", now=10)
                self.assertEqual(ledger.get("event-1")["status"], "queued")

                ledger.record_attempt("event-1", "sonar", now=11)
                row = ledger.get("event-1")
                self.assertEqual(row["status"], "delivering")
                self.assertEqual(row["attempts"], 1)

                ledger.mark_retrying("event-1", "HTTP_503", next_retry_at=20, now=12)
                row = ledger.get("event-1")
                self.assertEqual(row["status"], "retrying")
                self.assertEqual(row["last_error_code"], "HTTP_503")
                self.assertEqual(row["next_retry_at"], 20)

                ledger.record_attempt("event-1", "sonar", now=21)
                ledger.mark_transport_accepted("event-1", now=22)
                row = ledger.get("event-1")
                self.assertEqual(row["status"], "transport_accepted")
                self.assertEqual(row["attempts"], 2)
                self.assertEqual(row["transport_accepted"], 1)

                self.assertEqual(ledger.prune(retention_seconds=5, now=30), 1)
                self.assertIsNone(ledger.get("event-1"))
            finally:
                ledger.close()


class WatchdogTests(unittest.TestCase):
    def test_failure_threshold_and_recovery(self) -> None:
        state = watchdog.WatchdogState()
        self.assertEqual(watchdog.transition(state, ready=False, now=100), "none")
        self.assertEqual(watchdog.transition(state, ready=False, now=200), "none")
        self.assertEqual(watchdog.transition(state, ready=False, now=250), "failure")
        state.notified = True
        state.last_notice_at = 250
        self.assertEqual(watchdog.transition(state, ready=True, now=300), "recovery")
        self.assertEqual(state.failures, 0)
        self.assertFalse(state.notified)

    def test_state_round_trip_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "watchdog" / "state.json"
            state = watchdog.WatchdogState(
                failures=3, first_failure_at=10, notified=True, last_notice_at=20
            )
            watchdog.save_state(path, state)
            self.assertEqual(watchdog.load_state(path), state)
            self.assertEqual(path.stat().st_mode & 0o077, 0)

    def test_env_flag(self) -> None:
        with mock.patch.dict(os.environ, {"WATCHDOG_FLAG": "yes"}, clear=False):
            self.assertTrue(watchdog.env_flag("WATCHDOG_FLAG", False))
        with mock.patch.dict(os.environ, {"WATCHDOG_FLAG": "0"}, clear=False):
            self.assertFalse(watchdog.env_flag("WATCHDOG_FLAG", True))


if __name__ == "__main__":
    unittest.main()

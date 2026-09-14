from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from cloud import relay


class RelayTests(unittest.TestCase):
    def test_read_secret_requires_private_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secret"
            path.write_text("value\n", encoding="utf-8")
            path.chmod(0o600)
            self.assertEqual(relay.read_secret(path), "value")

            path.chmod(0o644)
            with self.assertRaises(RuntimeError):
                relay.read_secret(path)

    def test_normalize_sonar_event_is_bounded_and_safe(self) -> None:
        payload = {
            "project": {"name": "example", "url": "https://sonar.example/project"},
            "qualityGate": {"status": "ERROR"},
        }
        body = json.dumps(payload).encode()
        event_id, notification = relay.normalize_event("/webhooks/sonar", {}, body)

        self.assertEqual(event_id, hashlib.sha256(body).hexdigest())
        self.assertIsNotNone(notification)
        assert notification is not None
        self.assertEqual(notification["source"], "sonar")
        self.assertEqual(notification["severity"], "warning")
        self.assertEqual(notification["url"], "https://sonar.example/project")

    def test_github_webhook_is_acknowledged_without_forwarding(self) -> None:
        body = b'{"action":"completed"}'
        event_id, notification = relay.normalize_event(
            "/webhooks/github",
            {"X-GitHub-Event": "check_suite", "X-GitHub-Delivery": "delivery-1"},
            body,
        )
        self.assertEqual(event_id, "delivery-1")
        self.assertIsNone(notification)

    def test_durable_queue_deduplicates_and_persists_retry_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = relay.DurableQueue(Path(tmp) / "queue")
            notification = {"source": "sonar", "text": "status"}
            self.assertTrue(queue.enqueue("event-1", notification))
            self.assertFalse(queue.enqueue("event-1", notification))
            self.assertEqual(queue.depth(), 1)
            self.assertEqual(queue.pending_depth(), 1)

            path, item = queue.due(now=2**31)[0]
            queue.failed(path, item, error_code="HTTP_503", permanent=False)
            stored = relay.QueueItem.from_dict(json.loads(path.read_text(encoding="utf-8")))
            self.assertEqual(stored.status, "retrying")
            self.assertEqual(stored.attempts, 1)
            self.assertEqual(stored.last_error_code, "HTTP_503")

            queue.failed(path, stored, error_code="HTTP_400", permanent=True)
            self.assertEqual(queue.pending_depth(), 0)
            self.assertEqual(queue.permanent_failure_depth(), 1)

    def test_delivery_ledger_tracks_terminal_state_and_prunes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = relay.DeliveryLedger(Path(tmp) / "ledger.db")
            try:
                ledger.record_queued("event-1", "sonar", now=100)
                ledger.record_attempt("event-1", "sonar", now=110)
                ledger.mark_transport_accepted("event-1", now=120)
                row = ledger.get("event-1")
                assert row is not None
                self.assertEqual(row["status"], "transport_accepted")
                self.assertEqual(row["attempts"], 1)
                self.assertEqual(row["transport_accepted"], 1)
                self.assertEqual(ledger.prune(retention_seconds=10, now=1000), 1)
                self.assertIsNone(ledger.get("event-1"))
            finally:
                ledger.close()


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cloud import watchdog


class WatchdogTests(unittest.TestCase):
    def test_failure_threshold_and_recovery(self) -> None:
        state = watchdog.WatchdogState()
        self.assertEqual(watchdog.transition(state, ready=False, now=100), "none")
        self.assertEqual(watchdog.transition(state, ready=False, now=200), "none")
        self.assertEqual(watchdog.transition(state, ready=False, now=300), "failure")

        state.notified = True
        state.last_notice_at = 300
        self.assertEqual(watchdog.transition(state, ready=True, now=400), "recovery")
        self.assertEqual(state.failures, 0)
        self.assertEqual(state.first_failure_at, 0)
        self.assertFalse(state.notified)

    def test_elapsed_time_can_trigger_failure(self) -> None:
        state = watchdog.WatchdogState()
        self.assertEqual(watchdog.transition(state, ready=False, now=100), "none")
        self.assertEqual(watchdog.transition(state, ready=False, now=401), "failure")

    def test_notified_failure_waits_for_reminder_window(self) -> None:
        state = watchdog.WatchdogState(
            failures=3,
            first_failure_at=100,
            notified=True,
            last_notice_at=200,
        )
        self.assertEqual(watchdog.transition(state, ready=False, now=1000), "none")
        self.assertEqual(watchdog.transition(state, ready=False, now=22_000), "failure")

    def test_state_round_trip_is_atomic_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state" / "state.json"
            expected = watchdog.WatchdogState(
                failures=4,
                first_failure_at=10,
                notified=True,
                last_notice_at=20,
            )
            watchdog.save_state(path, expected)
            self.assertEqual(watchdog.load_state(path), expected)
            self.assertEqual(path.stat().st_mode & 0o077, 0)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""
Fixture-based tests for scripts/poll_patch_job.py, run against an in-memory
fake TPM client (NOT a real vendor's MCP server — see SKILL.md's Known
Limitations). Run directly:

    python3 tests/test_poll_patch_job.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from poll_patch_job import trigger_and_poll  # noqa: E402


class FakeClock:
    """Deterministic stand-in for time.monotonic()/time.sleep() so tests run instantly."""

    def __init__(self):
        self.now = 0.0
        self.sleep_calls = []

    def now_fn(self):
        return self.now

    def sleep_fn(self, seconds):
        self.sleep_calls.append(seconds)
        self.now += seconds


class FakeTpmClient:
    """Returns a scripted sequence of statuses, one per get_patch_job_status call."""

    def __init__(self, status_sequence, job_id="job-123"):
        self.status_sequence = list(status_sequence)
        self.job_id = job_id
        self.trigger_calls = []
        self.poll_calls = 0

    def trigger_patch_job(self, target_assets, cve_id=None, patch_id=None):
        self.trigger_calls.append(
            {"target_assets": target_assets, "cve_id": cve_id, "patch_id": patch_id}
        )
        return {"job_id": self.job_id}

    def get_patch_job_status(self, job_id):
        self.poll_calls += 1
        if self.status_sequence:
            status = self.status_sequence.pop(0)
        else:
            status = self.status_sequence[-1] if self.status_sequence else "failed"
        return {"status": status, "details": f"poll #{self.poll_calls}: {status}"}


class TriggerAndPollTests(unittest.TestCase):
    def test_passes_on_complete(self):
        client = FakeTpmClient(["pending", "in_progress", "complete"])
        clock = FakeClock()
        result = trigger_and_poll(
            client,
            target_assets=[{"hostname": "host1"}],
            cve_id="CVE-2026-00001",
            sleep_fn=clock.sleep_fn,
            now_fn=clock.now_fn,
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["job_id"], "job-123")
        self.assertEqual(client.poll_calls, 3)
        self.assertEqual(client.trigger_calls[0]["cve_id"], "CVE-2026-00001")

    def test_fails_on_failed_status(self):
        client = FakeTpmClient(["pending", "failed"])
        clock = FakeClock()
        result = trigger_and_poll(
            client,
            target_assets=[{"ip": "10.0.0.5"}],
            patch_id="KB123456",
            sleep_fn=clock.sleep_fn,
            now_fn=clock.now_fn,
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "failed")

    def test_fails_closed_on_unrecognized_status(self):
        """A vendor using different vocabulary (e.g. 'succeeded') must NOT read as a pass."""
        client = FakeTpmClient(["pending", "succeeded"])
        clock = FakeClock()
        result = trigger_and_poll(
            client,
            target_assets=[{"hostname": "host1"}],
            cve_id="CVE-2026-00001",
            sleep_fn=clock.sleep_fn,
            now_fn=clock.now_fn,
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "succeeded")

    def test_times_out_if_never_terminal(self):
        client = FakeTpmClient(["pending"] * 50)
        clock = FakeClock()
        result = trigger_and_poll(
            client,
            target_assets=[{"hostname": "host1"}],
            cve_id="CVE-2026-00001",
            timeout_seconds=30,
            sleep_fn=clock.sleep_fn,
            now_fn=clock.now_fn,
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "timeout")
        self.assertGreaterEqual(clock.now, 30)

    def test_backoff_increases_and_caps(self):
        client = FakeTpmClient(["pending"] * 10 + ["complete"])
        clock = FakeClock()
        trigger_and_poll(
            client,
            target_assets=[{"hostname": "host1"}],
            cve_id="CVE-2026-00001",
            timeout_seconds=10_000,
            sleep_fn=clock.sleep_fn,
            now_fn=clock.now_fn,
        )
        self.assertEqual(clock.sleep_calls[0], 5)
        self.assertEqual(clock.sleep_calls[1], 10)
        self.assertTrue(all(s <= 60 for s in clock.sleep_calls))
        self.assertGreater(len(clock.sleep_calls), 3)
        self.assertEqual(clock.sleep_calls[-1], 60)

    def test_rejects_empty_target_assets(self):
        client = FakeTpmClient(["complete"])
        with self.assertRaises(ValueError):
            trigger_and_poll(client, target_assets=[], cve_id="CVE-2026-00001")

    def test_rejects_missing_cve_and_patch_id(self):
        client = FakeTpmClient(["complete"])
        with self.assertRaises(ValueError):
            trigger_and_poll(client, target_assets=[{"hostname": "host1"}])

    def test_accepts_patch_id_without_cve_id(self):
        client = FakeTpmClient(["complete"])
        clock = FakeClock()
        result = trigger_and_poll(
            client,
            target_assets=[{"hostname": "host1"}],
            patch_id="KB123456",
            sleep_fn=clock.sleep_fn,
            now_fn=clock.now_fn,
        )
        self.assertTrue(result["passed"])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""
Fixture tests for patch_and_release.py — the gate that decides whether a
passing patch job actually releases SentinelOne containment. Most important
property under test: a failed or timed-out patch job must NEVER trigger a
reconnect call.

Usage:
    python3 tests/test_patch_and_release.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from patch_and_release import patch_and_release  # noqa: E402


class FakeTpmClient:
    def __init__(self, statuses):
        self._statuses = list(statuses)
        self.trigger_calls = []

    def trigger_patch_job(self, target_assets, cve_id=None, patch_id=None):
        self.trigger_calls.append((target_assets, cve_id, patch_id))
        return {"job_id": "job-1"}

    def get_patch_job_status(self, job_id):
        status = self._statuses.pop(0) if len(self._statuses) > 1 else self._statuses[0]
        return {"status": status, "details": f"status={status}"}


def no_sleep(_seconds):
    pass


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def advance_sleep(self, seconds):
        self.t += seconds


class TestPatchAndRelease(unittest.TestCase):
    def _call(self, statuses, reconnect_calls, confirm_reconnect=True, agent_id="agent-1",
               console_url="https://tenant.sentinelone.net", api_token="tok", reconnect_fn=None):
        client = FakeTpmClient(statuses)
        clock = FakeClock()

        def fake_reconnect(console_url_, api_token_, agent_id_):
            reconnect_calls.append((console_url_, api_token_, agent_id_))

        return patch_and_release(
            tpm_client=client,
            target_assets=[{"hostname": "host1"}],
            agent_id=agent_id,
            cve_id="CVE-2026-XXXXX",
            console_url=console_url,
            api_token=api_token,
            confirm_reconnect=confirm_reconnect,
            sleep_fn=no_sleep,
            now_fn=clock.now,
            reconnect_fn=reconnect_fn if reconnect_fn is not None else fake_reconnect,
        )

    def test_passing_job_with_confirm_reconnects(self):
        reconnect_calls = []
        result = self._call(["complete"], reconnect_calls)
        self.assertTrue(result["passed"])
        self.assertTrue(result["released"])
        self.assertIsNone(result["release_error"])
        self.assertEqual(reconnect_calls, [("https://tenant.sentinelone.net", "tok", "agent-1")])

    def test_failed_job_never_reconnects(self):
        reconnect_calls = []
        result = self._call(["failed"], reconnect_calls)
        self.assertFalse(result["passed"])
        self.assertFalse(result["released"])
        self.assertEqual(reconnect_calls, [])

    def test_unrecognized_status_never_reconnects(self):
        reconnect_calls = []
        result = self._call(["succeeded"], reconnect_calls)  # vendor using different vocabulary
        self.assertFalse(result["passed"])
        self.assertFalse(result["released"])
        self.assertEqual(reconnect_calls, [])

    def test_passing_job_without_confirm_stays_isolated_by_design(self):
        reconnect_calls = []
        result = self._call(["complete"], reconnect_calls, confirm_reconnect=False)
        self.assertTrue(result["passed"])
        self.assertFalse(result["released"])
        self.assertIn("confirm_reconnect=False", result["release_error"])
        self.assertEqual(reconnect_calls, [])

    def test_passing_job_without_credentials_stays_isolated(self):
        reconnect_calls = []
        result = self._call(["complete"], reconnect_calls, console_url=None, api_token=None)
        self.assertTrue(result["passed"])
        self.assertFalse(result["released"])
        self.assertIn("not provided", result["release_error"])
        self.assertEqual(reconnect_calls, [])

    def test_reconnect_failure_reported_agent_may_still_be_isolated(self):
        def failing_reconnect(console_url_, api_token_, agent_id_):
            raise RuntimeError("HTTP 403")

        result = self._call(["complete"], [], reconnect_fn=failing_reconnect)
        self.assertTrue(result["passed"])
        self.assertFalse(result["released"])
        self.assertIn("may still be isolated", result["release_error"])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""
Fixture tests for reconnect_agent.py, mirroring the rigor applied to
tenable-sentinelone-attack-path-interruption's isolate_agent.py tests. Mocks
urllib so no real network call is made.

Usage:
    python3 tests/test_reconnect_agent.py
"""
import io
import json
import os
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import reconnect_agent  # noqa: E402


class FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestReconnect(unittest.TestCase):
    def test_reconnect_returns_parsed_json_on_success(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse({"affected": 1})):
            result = reconnect_agent.reconnect("https://tenant.sentinelone.net", "tok", "agent-1")
        self.assertEqual(result, {"affected": 1})

    def test_reconnect_calls_connect_endpoint_with_expected_body(self):
        captured = {}

        def fake_urlopen(req, timeout=30):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data)
            captured["auth"] = req.get_header("Authorization")
            return FakeResponse({"affected": 1})

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            reconnect_agent.reconnect("https://tenant.sentinelone.net/", "tok-123", "agent-42")

        self.assertEqual(captured["url"], "https://tenant.sentinelone.net/web/api/v2.1/agents/actions/connect")
        self.assertEqual(captured["body"], {"filter": {"ids": ["agent-42"]}})
        self.assertEqual(captured["auth"], "ApiToken tok-123")


class TestMainErrorHandling(unittest.TestCase):
    def _run_main(self, argv, env):
        with mock.patch.object(sys, "argv", ["reconnect_agent.py"] + argv), \
             mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("sys.stdout", new_callable=io.StringIO), \
             mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            try:
                reconnect_agent.main()
            except SystemExit as e:
                return e.code, err.getvalue()
            return 0, err.getvalue()

    def test_dry_run_without_confirm_makes_no_call(self):
        with mock.patch("reconnect_agent.reconnect") as fake_reconnect:
            code, _ = self._run_main(["agent-1", "--reason", "test"], {})
        fake_reconnect.assert_not_called()
        self.assertEqual(code, 0)

    def test_confirm_without_env_vars_exits_nonzero(self):
        code, err = self._run_main(["agent-1", "--reason", "test", "--confirm"], {})
        self.assertNotEqual(code, 0)
        self.assertIn("SENTINELONE_CONSOLE_URL", err)

    def test_http_error_reported_and_agent_treated_as_still_isolated(self):
        env = {"SENTINELONE_CONSOLE_URL": "https://tenant.sentinelone.net", "SENTINELONE_API_TOKEN": "tok"}
        http_err = urllib.error.HTTPError(
            "https://tenant.sentinelone.net/web/api/v2.1/agents/actions/connect",
            403,
            "Forbidden",
            {},
            io.BytesIO(b'{"error":"forbidden"}'),
        )
        with mock.patch("reconnect_agent.reconnect", side_effect=http_err):
            code, err = self._run_main(["agent-1", "--reason", "test", "--confirm"], env)
        self.assertNotEqual(code, 0)
        self.assertIn("FAILED", err)
        self.assertIn("may still be isolated", err)

    def test_success_does_not_claim_proof_of_reconnection(self):
        env = {"SENTINELONE_CONSOLE_URL": "https://tenant.sentinelone.net", "SENTINELONE_API_TOKEN": "tok"}
        with mock.patch("reconnect_agent.reconnect", return_value={"affected": 1}), \
             mock.patch.object(sys, "argv", ["reconnect_agent.py", "agent-1", "--reason", "test", "--confirm"]), \
             mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            try:
                reconnect_agent.main()
            except SystemExit:
                pass
        self.assertIn("Do not treat this response alone as proof", out.getvalue())


if __name__ == "__main__":
    unittest.main()

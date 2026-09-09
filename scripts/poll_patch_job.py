#!/usr/bin/env python3
"""
Reference implementation of the trigger-and-poll orchestration described in
the tenable-patch-remediation-bridge skill's Phase 2. Demonstrates the
backoff/timeout/status-mapping logic against any object exposing
trigger_patch_job(target_assets, cve_id=None, patch_id=None) -> {"job_id": str}
and get_patch_job_status(job_id) -> {"status": str, "details": str | None} —
the same two-tool contract described in SKILL.md.

*** NOT LIVE-VERIFIED AGAINST A REAL TPM. ***
No patch_*/adaptiva/tpm-named MCP tool exists on any server available while
building this skill. tests/test_poll_patch_job.py exercises this logic
against an in-memory fake client, not a real vendor's API. Confirm the exact
tool/field names against whichever TPM MCP server you actually connect
before relying on this.

Usage (library, not a standalone CLI — a real caller wires trigger_client to
actual MCP tool calls):
    from poll_patch_job import trigger_and_poll

    result = trigger_and_poll(
        client=my_mcp_client,
        target_assets=[{"hostname": "host1"}, {"ip": "10.0.0.5"}],
        cve_id="CVE-2026-XXXXX",
        timeout_seconds=1800,
    )
    # result["passed"] is True only if the job reached "complete"
"""
import time

TERMINAL_PASS = "complete"
TERMINAL_FAIL = "failed"
KNOWN_STATUSES = {"pending", "in_progress", TERMINAL_PASS, TERMINAL_FAIL}

INITIAL_BACKOFF_SECONDS = 5
MAX_BACKOFF_SECONDS = 60
BACKOFF_MULTIPLIER = 2


def trigger_and_poll(
    client,
    target_assets,
    cve_id=None,
    patch_id=None,
    timeout_seconds=1800,
    sleep_fn=time.sleep,
    now_fn=time.monotonic,
):
    """
    Calls client.trigger_patch_job(...), then polls
    client.get_patch_job_status(job_id) with exponential backoff until a
    terminal status or timeout. Returns:
        {"passed": bool, "status": str, "details": str | None, "job_id": str}

    `client` must implement trigger_patch_job(target_assets, cve_id=None,
    patch_id=None) -> {"job_id": str} and get_patch_job_status(job_id) ->
    {"status": str, "details": str | None}.

    Fails closed: any status not in KNOWN_STATUSES is treated as failed
    (passed=False), never as a pass, and a timeout is also a failure —
    a job that never reaches a terminal status is not a pass by default.
    """
    if not target_assets:
        raise ValueError("target_assets must not be empty")
    if not cve_id and not patch_id:
        raise ValueError("at least one of cve_id or patch_id is required")

    trigger_result = client.trigger_patch_job(
        target_assets=target_assets, cve_id=cve_id, patch_id=patch_id
    )
    job_id = trigger_result["job_id"]

    deadline = now_fn() + timeout_seconds
    backoff = INITIAL_BACKOFF_SECONDS
    last_status = None
    last_details = None

    while True:
        poll_result = client.get_patch_job_status(job_id)
        last_status = poll_result.get("status")
        last_details = poll_result.get("details")

        if last_status == TERMINAL_PASS:
            return {"passed": True, "status": last_status, "details": last_details, "job_id": job_id}
        if last_status == TERMINAL_FAIL or last_status not in KNOWN_STATUSES:
            return {"passed": False, "status": last_status, "details": last_details, "job_id": job_id}

        if now_fn() >= deadline:
            return {
                "passed": False,
                "status": "timeout",
                "details": f"last observed status was {last_status!r} before timeout",
                "job_id": job_id,
            }

        sleep_fn(min(backoff, MAX_BACKOFF_SECONDS, max(0, deadline - now_fn())))
        backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF_SECONDS)

#!/usr/bin/env python3
"""
Composes this skill's two steps into the actual CTEM-loop gate: trigger a
patch job on a generic TPM (poll_patch_job.trigger_and_poll), and only on an
explicit "complete" status call SentinelOne's reconnect endpoint
(reconnect_agent.reconnect) to release containment. A failed or timed-out
patch job never reconnects the agent — it stays isolated.

This function does NOT call a Tenable rescan itself — per SKILL.md, a
"complete" status from the TPM is not independent proof the patch actually
applied. The calling workflow is expected to run the Tenable rescan between
a passing patch job and calling this, or to treat this function's result as
one input alongside the rescan result, not a replacement for it.

Usage (library — a real caller wires tpm_client to actual MCP tool calls):
    from patch_and_release import patch_and_release

    result = patch_and_release(
        tpm_client=my_mcp_client,
        target_assets=[{"hostname": "host1"}],
        agent_id="<sentinelone_agent_id>",
        cve_id="CVE-2026-XXXXX",
        console_url=os.environ["SENTINELONE_CONSOLE_URL"],
        api_token=os.environ["SENTINELONE_API_TOKEN"],
        confirm_reconnect=True,
    )
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from poll_patch_job import trigger_and_poll  # noqa: E402
from reconnect_agent import reconnect  # noqa: E402


def patch_and_release(
    tpm_client,
    target_assets,
    agent_id,
    cve_id=None,
    patch_id=None,
    console_url=None,
    api_token=None,
    confirm_reconnect=False,
    timeout_seconds=1800,
    sleep_fn=None,
    now_fn=None,
    reconnect_fn=reconnect,
):
    """
    Returns:
        {"passed": bool, "released": bool, "status": str, "details": str|None,
         "job_id": str, "release_error": str|None}

    released is True only when the patch job passed AND the reconnect call
    was actually made and did not raise. If confirm_reconnect is False (the
    default — matches reconnect_agent.py's own --confirm gate), a passing
    patch job is reported but the agent is deliberately left isolated and
    released=False, details say why.
    """
    poll_kwargs = {}
    if sleep_fn is not None:
        poll_kwargs["sleep_fn"] = sleep_fn
    if now_fn is not None:
        poll_kwargs["now_fn"] = now_fn

    poll_result = trigger_and_poll(
        client=tpm_client,
        target_assets=target_assets,
        cve_id=cve_id,
        patch_id=patch_id,
        timeout_seconds=timeout_seconds,
        **poll_kwargs,
    )

    result = {**poll_result, "released": False, "release_error": None}

    if not poll_result["passed"]:
        return result

    if not confirm_reconnect:
        result["release_error"] = "confirm_reconnect=False — agent left isolated by design, no reconnect attempted"
        return result

    if not console_url or not api_token:
        result["release_error"] = "SENTINELONE_CONSOLE_URL/SENTINELONE_API_TOKEN not provided — agent left isolated"
        return result

    try:
        reconnect_fn(console_url, api_token, agent_id)
        result["released"] = True
    except Exception as e:  # noqa: BLE001 - deliberately broad: any failure here must not be swallowed
        result["release_error"] = f"reconnect call failed, agent may still be isolated: {e}"

    return result

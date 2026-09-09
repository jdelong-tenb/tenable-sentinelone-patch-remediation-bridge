---
name: tenable-sentinelone-patch-remediation-bridge
description: Bridges a Tenable-detected vulnerability to any third-party patch management (TPM) tool's MCP server via a small, vendor-neutral contract, polls the resulting job to a pass/fail signal, and — only on an explicit pass, with confirmation — calls SentinelOne's REST API to release containment on the patched host. Invoke when someone says things like "trigger a patch job for this CVE," "patch these hosts and tell me when it's done," "did the patch job finish before we rescan," or "release containment now that it's patched."
---

# Tenable + SentinelOne Patch Remediation Bridge

## Why this exists

A closed CTEM remediation loop — detect a vulnerability, contain the affected host, patch it, verify the fix, release containment — needs a "patch" step that talks to whatever patch management tool the customer actually runs (Adaptiva, Tanium, BigFix, SCCM, or something else), and a release step that hands containment back to SentinelOne once the patch is confirmed. There is no single standard patch-management API, so this skill defines a **small, vendor-neutral MCP tool contract** (below) for the patch leg and orchestrates against *any* MCP server that implements it — the same way [`tenable-sentinelone-attack-path-interruption`](https://github.com/jdelong-tenb/tenable-sentinelone-attack-path-interruption)'s `isolate_agent.py` calls SentinelOne's REST API directly instead of assuming a pre-built abstraction existed. The release leg calls that same SentinelOne REST surface directly (not through `purple-mcp`, which is read-only), completing the loop that [`tenable-sentinelone-attack-path-interruption`](https://github.com/jdelong-tenb/tenable-sentinelone-attack-path-interruption) opened.

This is a community-built skill, not official guidance from Tenable or SentinelOne. **This skill never patches anything itself** — it only calls a tool that some other, already-configured MCP server exposes for the patch step. It only reconnects a SentinelOne agent when the patch job it triggered explicitly passed.

## The contract (patch step)

Any TPM integration this skill can drive must expose two MCP tools matching this shape (exact tool name can vary — see "Finding the right tool" below):

**Trigger a patch job**
```
trigger_patch_job(
  target_assets: list[{"hostname": str} | {"ip": str}],  # at least one identifier per asset
  cve_id: str | None,      # e.g. "CVE-2026-XXXXX" — the vulnerability driving this job
  patch_id: str | None,    # vendor-specific patch/update identifier, if cve_id isn't enough
) -> {"job_id": str}
```
At least one of `cve_id` or `patch_id` must be supplied. `target_assets` must not be empty.

**Poll job status**
```
get_patch_job_status(job_id: str) -> {
  "status": "pending" | "in_progress" | "complete" | "failed",
  "details": str | None,   # vendor-specific message, surfaced to the user on failure
}
```

This skill treats any status outside those four literal values as `failed` (fail closed, not open) and surfaces the raw value in its output so the mismatch is visible rather than silently swallowed.

## The release step (SentinelOne)

`scripts/reconnect_agent.py` calls `POST /web/api/v2.1/agents/actions/connect` directly against the SentinelOne Management Console API — the mirror of `isolate_agent.py`'s `disconnect` call. This endpoint and body shape (`{"filter": {"ids": [agent_id]}}`) were **live-verified once**, 2026-07-18, in a round-trip disconnect/reconnect test against a real SentinelOne tenant (a single home-lab agent, chosen specifically to carry no shared blast radius), confirmed via the agent's `networkStatus` field flipping `disconnected` → `connected`. That is one successful call on one date, not a standing guarantee — confirm the exact path, auth header, and body shape against your tenant's current API reference before relying on this in a new environment. Like `isolate_agent.py`, this defaults to a dry run and requires `--confirm`.

## Phase 1 — Find the right tool

List the MCP tools available in the current session and look for a `trigger_patch_job`/`get_patch_job_status` pair (naming may be prefixed by server, e.g. `mcp__adaptiva__trigger_patch_job`). **Do not assume a specific server is connected** — this skill has no fixed dependency on any one TPM vendor. If no matching tool pair exists, tell the user plainly that no TPM MCP server implementing this contract is connected, and stop — do not fall back to guessing at some other tool's shape.

**Example user prompts:**
- "What patch tools do I have connected?"
- "Is there a TPM MCP server hooked up right now?"

## Phase 2 — Trigger and poll

Once a matching tool pair is found:

1. Confirm with the user the exact target assets and the CVE/patch driving the job before calling `trigger_patch_job` — this commits a change on the customer's infrastructure, the same confirm-before-act bar as containment actions in the companion skills.
2. Call `trigger_patch_job` and record the returned `job_id`.
3. Use `scripts/poll_patch_job.py`'s `trigger_and_poll()` logic (or reimplement the same backoff/timeout behavior directly through the MCP tool calls) to call `get_patch_job_status` repeatedly until it returns `complete` or `failed`, or a caller-supplied timeout elapses.
4. Report a clean pass/fail signal — `complete` → pass, `failed` or timeout → fail — plus the last `details` message. Never report "patched" without an explicit `complete` status.

**Example user prompts:**
- "Trigger a patch job for CVE-2026-XXXXX on these three hosts"
- "Has the patch job finished? Don't rescan until it has."

## Phase 3 — Release containment (only on a confirmed pass)

After Phase 2 reports `passed: true`, and after the calling CTEM-loop workflow's own Tenable rescan (if any) has also confirmed the fix — this skill does not run that rescan itself:

1. Confirm with the user the exact SentinelOne agent ID to release, same confirm-before-act bar as Phase 2's trigger step and as `isolate_agent.py`'s isolation call.
2. Use `scripts/patch_and_release.py`'s `patch_and_release()` (which composes Phase 2's poll with the reconnect call under one gate) or call `scripts/reconnect_agent.py`'s `reconnect()` directly with `--confirm`.
3. A `failed`, timed-out, or unrecognized-status patch job **must never** reach this step — the agent stays isolated. `patch_and_release()` enforces this: it only calls reconnect when `passed` is `True` and the caller explicitly set `confirm_reconnect=True`.
4. Report `released: true` only when the reconnect call actually succeeded — an HTTP error, network error, or bad response means the agent's true state is unknown; say so plainly and tell the user to verify in the SentinelOne console rather than assuming success or failure.

**Example user prompts:**
- "Patch job passed, release the host from quarantine"
- "Rescan came back clean, unquarantine it now"

## MCP tools used

- `trigger_patch_job` — on whatever MCP server the customer has connected for their patch management tool (exact server name varies; not bundled with or specific to this skill)
- `get_patch_job_status` — same server, polled per Phase 2
- No SentinelOne MCP tool is used for the release step — `purple-mcp` is read-only and has no reconnect tool, so `reconnect_agent.py` calls the SentinelOne Management Console REST API directly, same as `isolate_agent.py` does for isolation.

## Scripts

- `scripts/poll_patch_job.py` — pure-stdlib reference implementation of the poll-with-backoff-to-pass/fail logic (Phase 2), tested against an in-memory fake TPM client in `tests/test_poll_patch_job.py`. **Scaffold-only against the TPM side** — no `patch_*`/`adaptiva`/`tpm`-named tool exists on any MCP server available while building this skill, so the contract was designed from the CTEM-loop demo's requirements, not observed live traffic from a real vendor. Confirm the exact tool/field names against whichever TPM MCP server you actually connect before relying on this in a real environment.
- `scripts/reconnect_agent.py` — direct SentinelOne REST call for the release step (Phase 3), tested with mocked `urllib` in `tests/test_reconnect_agent.py`. Endpoint live-verified once (see "The release step" above).
- `scripts/patch_and_release.py` — composes the two into the actual gate: pass → reconnect (if confirmed), fail/timeout/unrecognized → agent stays isolated, no reconnect attempted. Tested in `tests/test_patch_and_release.py`, including the failure-must-not-reconnect property.

## Known limitations

- **No live TPM MCP server exists to test against.** The two-tool patch contract is a design proposal, not something observed working against a real vendor's MCP server. Treat `poll_patch_job.py` as scaffolding that demonstrates the polling/backoff/status logic against a fake in-memory server, not as proof the contract matches any real TPM's actual API.
- **This skill cannot patch anything if no MCP server implements the contract.** It has no vendor-specific fallback for the patch step because there is no single "the" patch-management REST API to fall back to — every vendor's is different. If you need this to work today against a specific vendor (e.g. Adaptiva), someone has to build or point at an MCP server exposing this contract for that vendor first.
- **The SentinelOne reconnect endpoint has only one real-world verification.** One successful call, one tenant, one date (2026-07-18). SentinelOne's API can and does change versions — confirm the current API reference before relying on this in a new tenant.
- **`trigger_patch_job` and the SentinelOne reconnect call are both real, consequential actions** on customer infrastructure. Always confirm target assets/CVE and the exact agent ID with the user before calling either — never trigger a job, and never release containment, on a match alone.
- **A "complete" status is only as trustworthy as the underlying TPM's own reporting.** This skill does not independently verify a patch actually applied — that's what the CTEM loop's Tenable remediation rescan is for. Don't release containment on the strength of a "complete" status alone; wait for the rescan too.
- **Fail-closed on unrecognized status values, on both ends.** A TPM status outside `pending`/`in_progress`/`complete`/`failed` is treated as failed, and a reconnect call that errors is reported as "agent may still be isolated," never as a silent success. Check the raw status/error in the output if something that should have succeeded reports as failed.

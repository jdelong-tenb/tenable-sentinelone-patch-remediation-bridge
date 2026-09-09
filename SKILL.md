---
name: tenable-patch-remediation-bridge
description: Bridges a Tenable-detected vulnerability to any third-party patch management (TPM) tool's MCP server via a small, vendor-neutral contract, then polls the resulting job to a pass/fail signal Tenable can gate a remediation rescan on. Invoke when someone says things like "trigger a patch job for this CVE," "patch these hosts and tell me when it's done," or "did the patch job finish before we rescan."
---

# Tenable Patch Remediation Bridge

## Why this exists

A closed remediation loop — detect a vulnerability, contain the affected host, patch it, verify the fix, release containment — needs a "patch" step that talks to whatever patch management tool the customer actually runs (Adaptiva, Tanium, BigFix, SCCM, or something else). There is no single standard patch-management API, and hardcoding this skill to one vendor would make it useless everywhere else. Instead, this skill defines a **small, vendor-neutral MCP tool contract** (below) and orchestrates against *any* MCP server that implements it — the same way [`tenable-sentinelone-attack-path-interruption`](https://github.com/jdelong-tenb/tenable-sentinelone-attack-path-interruption)'s `isolate_agent.py` calls SentinelOne's REST API directly instead of assuming a pre-built abstraction existed.

This is a community-built skill, not official guidance from Tenable or any patch-management vendor. **This skill never patches anything itself** — it only calls a tool that some other, already-configured MCP server exposes. If no MCP server on the session exposes the contract below, say so plainly rather than attempting to approximate patching some other way.

## The contract

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

## Phase 1 — Find the right tool

List the MCP tools available in the current session and look for a `trigger_patch_job`/`get_patch_job_status` pair (naming may be prefixed by server, e.g. `mcp__adaptiva__trigger_patch_job`). **Do not assume a specific server is connected** — this skill has no fixed dependency on any one vendor. If no matching tool pair exists, tell the user plainly that no TPM MCP server implementing this contract is connected, and stop — do not fall back to guessing at some other tool's shape.

**Example user prompts:**
- "What patch tools do I have connected?"
- "Is there a TPM MCP server hooked up right now?"

## Phase 2 — Trigger and poll

Once a matching tool pair is found:

1. Confirm with the user the exact target assets and the CVE/patch driving the job before calling `trigger_patch_job` — this commits a change on the customer's infrastructure, the same confirm-before-act bar as containment actions in the companion skills.
2. Call `trigger_patch_job` and record the returned `job_id`.
3. Use `scripts/poll_patch_job.py`'s `poll_until_terminal()` logic (or reimplement the same backoff/timeout behavior directly through the MCP tool calls) to call `get_patch_job_status` repeatedly until it returns `complete` or `failed`, or a caller-supplied timeout elapses.
4. Report a clean pass/fail signal — `complete` → pass, `failed` or timeout → fail — plus the last `details` message. This is the signal the calling CTEM-loop workflow (Tenable rescan → SentinelOne unquarantine) gates on; never report "patched" without an explicit `complete` status.

**Example user prompts:**
- "Trigger a patch job for CVE-2026-XXXXX on these three hosts"
- "Has the patch job finished? Don't rescan until it has."

## MCP tools used

- `trigger_patch_job` — on whatever MCP server the customer has connected for their patch management tool (exact server name varies; not bundled with or specific to this skill)
- `get_patch_job_status` — same server, polled per Phase 2

## `scripts/poll_patch_job.py`

A pure-stdlib reference implementation of the poll-with-backoff-to-pass/fail logic described in Phase 2, plus a small in-memory fake TPM server used by `tests/test_poll_patch_job.py` to prove the backoff, timeout, and status-mapping logic actually works. **This is scaffold-only, not verified against a live TPM MCP server** — no `patch_*`/`adaptiva`/`tpm`-named tool exists on any MCP server available while building this skill, so the contract above was designed from the CTEM-loop demo's requirements, not observed live traffic from a real vendor. Confirm the exact tool/field names against whichever TPM MCP server you actually connect before relying on this in a real environment.

## Known limitations

- **No live TPM MCP server exists to test against.** The two-tool contract above is a design proposal, not something observed working against a real vendor's MCP server. Treat `poll_patch_job.py` as scaffolding that demonstrates the polling/backoff/status logic against a fake in-memory server, not as proof the contract matches any real TPM's actual API.
- **This skill cannot patch anything if no MCP server implements the contract.** It has no vendor-specific fallback (unlike the SentinelOne skills' direct-REST-call fallback) because there is no single "the" patch-management REST API to fall back to — every vendor's is different. If you need this to work today against a specific vendor (e.g. Adaptiva), someone has to build or point at an MCP server exposing this contract for that vendor first.
- **`trigger_patch_job` is a real, consequential action** on customer infrastructure (deploying patches, which can require reboots or break things). Always confirm target assets and the driving CVE/patch with the user before calling it — never trigger a job on a match alone.
- **A "complete" status is only as trustworthy as the underlying TPM's own reporting.** This skill does not independently verify a patch actually applied — that's what the CTEM loop's next step (a Tenable remediation rescan) is for. Don't skip the rescan on the strength of a "complete" status alone.
- **Fail-closed on unrecognized status values.** If a TPM MCP server returns a status string outside `pending`/`in_progress`/`complete`/`failed`, this skill treats it as failed rather than guessing it means success — but that also means a vendor using slightly different vocabulary (e.g. `"succeeded"` instead of `"complete"`) will read as a false failure until the adapter is corrected. Check the raw status in the output if a job that should have succeeded reports failed.

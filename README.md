# Tenable Patch Remediation Bridge

A Claude Code skill that bridges a Tenable-detected vulnerability to any third-party patch management (TPM) tool's MCP server via a small, vendor-neutral contract, then polls the resulting job to a pass/fail signal Tenable can gate a remediation rescan on.

## What it does

A closed remediation loop — detect, contain, patch, verify, release — needs a "patch" step, but there is no single standard patch-management API across vendors (Adaptiva, Tanium, BigFix, SCCM, ...). Rather than hardcode to one vendor, this skill defines two MCP tools any TPM integration can implement:

- `trigger_patch_job(target_assets, cve_id, patch_id) -> {job_id}`
- `get_patch_job_status(job_id) -> {status, details}`

and orchestrates against whichever MCP server on the session actually exposes them. This skill:

1. **Looks for the contract** among the session's connected MCP tools — does not assume any specific vendor is configured.
2. **Confirms the target** (assets + driving CVE/patch) with the user before triggering anything — this is a consequential action on real infrastructure.
3. **Triggers the job**, then polls it to a terminal status with exponential backoff and a timeout.
4. **Reports a clean pass/fail signal** — `complete` only, fails closed on `failed`, timeout, or any unrecognized status string — for a calling workflow (e.g. a Tenable rescan → SentinelOne unquarantine loop) to gate on.

This is a community-built skill, not official guidance from Tenable or any patch-management vendor. **It never patches anything itself** — it only calls a tool some other, already-configured MCP server exposes.

## Prerequisites

- Claude Code (or another skill-compatible client) with an MCP server connected that implements the two-tool contract above for your patch management tool. **No such server is bundled with this skill** — you (or your TPM vendor) need one that exposes `trigger_patch_job`/`get_patch_job_status` matching the shapes in [SKILL.md](SKILL.md#the-contract).
- Python 3 (stdlib only, no third-party dependencies) if you want to run `scripts/poll_patch_job.py` or its tests directly.

## How to run

1. Copy or symlink this directory into your Claude Code skills path:
   ```bash
   cp -r tenable-patch-remediation-bridge ~/.claude/skills/
   ```
2. Connect an MCP server that implements the contract for your patch management tool.
3. In a Claude Code session, say something like:
   - "Trigger a patch job for CVE-2026-XXXXX on these three hosts"
   - "Has the patch job finished? Don't rescan until it has."

The skill activates automatically from its description, or you can invoke it explicitly.

`scripts/poll_patch_job.py` is a reference implementation of the trigger-and-poll logic described in SKILL.md Phase 2. **It is scaffolding, not a verified integration** — no real TPM MCP server was available to test against while building this skill; `tests/test_poll_patch_job.py` exercises the same logic against an in-memory fake client instead. Run the tests with:
```bash
python3 tests/test_poll_patch_job.py -v
```

## What it produces

- A `job_id` for the triggered patch job
- A pass/fail verdict (`passed: true` only on an explicit `complete` status; `failed`, timeout, or any unrecognized status all report `passed: false`) plus the last status/details message
- Nothing else — this skill does not itself verify the patch worked; that's the calling workflow's rescan step

## Known limitations

See [SKILL.md Known Limitations](SKILL.md#known-limitations) — most importantly: the two-tool contract is a design proposal validated only against an in-memory fake client, not any real vendor's API, and this skill has no vendor-specific fallback if no MCP server implements the contract (there is no single "the" patch-management REST API to fall back to the way the SentinelOne skills can fall back to a direct S1 REST call).

## License

MIT — see [LICENSE](LICENSE).

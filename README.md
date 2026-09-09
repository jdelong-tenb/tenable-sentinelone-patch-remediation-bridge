# Tenable + SentinelOne Patch Remediation Bridge

A Claude Code skill that bridges a Tenable-detected vulnerability to any third-party patch management (TPM) tool's MCP server via a small, vendor-neutral contract, polls the resulting job to a pass/fail signal, and — only on an explicit pass, with confirmation — calls SentinelOne's REST API to release containment on the patched host.

## What it does

A closed CTEM remediation loop — detect, contain, patch, verify, release — needs a "patch" step and a "release" step. There is no single standard patch-management API across vendors (Adaptiva, Tanium, BigFix, SCCM, ...), so rather than hardcode the patch step to one vendor, this skill defines two MCP tools any TPM integration can implement:

- `trigger_patch_job(target_assets, cve_id, patch_id) -> {job_id}`
- `get_patch_job_status(job_id) -> {status, details}`

and orchestrates against whichever MCP server on the session actually exposes them. The release step then calls SentinelOne's Management Console REST API directly (`purple-mcp` is read-only and has no reconnect tool), mirroring how [`tenable-sentinelone-attack-path-interruption`](https://github.com/jdelong-tenb/tenable-sentinelone-attack-path-interruption) calls SentinelOne for isolation. This skill:

1. **Looks for the patch contract** among the session's connected MCP tools — does not assume any specific TPM vendor is configured.
2. **Confirms the target** (assets + driving CVE/patch) with the user before triggering anything — this is a consequential action on real infrastructure.
3. **Triggers the patch job**, then polls it to a terminal status with exponential backoff and a timeout.
4. **Reports a clean pass/fail signal** — `complete` only, fails closed on `failed`, timeout, or any unrecognized status string.
5. **On an explicit pass, and only with confirmation**, calls SentinelOne to release containment on the agent — a failed/timed-out/unrecognized-status job never reaches this step; the agent stays isolated.

This is a community-built skill, not official guidance from Tenable or SentinelOne. **The patch step never patches anything itself** — it only calls a tool some other, already-configured MCP server exposes.

## Prerequisites

- Claude Code (or another skill-compatible client) with an MCP server connected that implements the two-tool contract above for your patch management tool. **No such server is bundled with this skill** — you (or your TPM vendor) need one that exposes `trigger_patch_job`/`get_patch_job_status` matching the shapes in [SKILL.md](SKILL.md#the-contract-patch-step).
- A SentinelOne Management Console API token (`SENTINELONE_API_TOKEN`) and console URL (`SENTINELONE_CONSOLE_URL`) for the release step — same credentials pattern as `tenable-sentinelone-attack-path-interruption`'s `isolate_agent.py`.
- Python 3 (stdlib only, no third-party dependencies) to run the scripts or their tests directly.

## How to run

1. Copy or symlink this directory into your Claude Code skills path:
   ```bash
   cp -r tenable-sentinelone-patch-remediation-bridge ~/.claude/skills/
   ```
2. Connect an MCP server that implements the patch contract for your TPM vendor.
3. Export `SENTINELONE_CONSOLE_URL` / `SENTINELONE_API_TOKEN` for the release step.
4. In a Claude Code session, say something like:
   - "Trigger a patch job for CVE-2026-XXXXX on these three hosts"
   - "Has the patch job finished? Don't rescan until it has."
   - "Rescan came back clean, release the host from quarantine"

The skill activates automatically from its description, or you can invoke it explicitly.

`scripts/poll_patch_job.py` is a reference implementation of the trigger-and-poll logic (Phase 2). **The TPM side is scaffolding, not a verified integration** — no real TPM MCP server was available to test against while building this skill; `tests/test_poll_patch_job.py` exercises the same logic against an in-memory fake client instead. `scripts/reconnect_agent.py` is the release step — its endpoint was live-verified once against a real SentinelOne tenant (see [SKILL.md](SKILL.md#the-release-step-sentinelone)); `tests/test_reconnect_agent.py` mocks the HTTP call. `scripts/patch_and_release.py` composes both under one gate; `tests/test_patch_and_release.py` proves a failed patch job never reconnects the agent. Run all four suites with:
```bash
for f in tests/test_*.py; do python3 "$f" -v; done
```

## What it produces

- A `job_id` for the triggered patch job
- A pass/fail verdict (`passed: true` only on an explicit `complete` status; `failed`, timeout, or any unrecognized status all report `passed: false`) plus the last status/details message
- On a pass, with confirmation: `released: true` only if the SentinelOne reconnect call actually succeeded; otherwise `release_error` explains why the agent may still be isolated
- Nothing else — this skill does not itself run the Tenable rescan that should sit between a passing patch job and releasing containment

## Known limitations

See [SKILL.md Known Limitations](SKILL.md#known-limitations) — most importantly: the patch-step contract is a design proposal validated only against an in-memory fake client, not any real vendor's API, and the SentinelOne reconnect endpoint has exactly one real-world verification (one tenant, one date).

## License

MIT — see [LICENSE](LICENSE).

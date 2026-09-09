---
name: "Tenable Patch Remediation Bridge"
author: "jdelong-tenb"
github_url: "https://github.com/jdelong-tenb/tenable-patch-remediation-bridge"
description: "Bridges a Tenable-detected vulnerability to any third-party patch management tool's MCP server via a small, vendor-neutral contract, then polls the resulting job to a pass/fail signal Tenable can gate a remediation rescan on."
license: "MIT"
tier: "contributed"
tags: ["patch-management", "remediation", "ctem", "vulnerability-management", "mcp-bridge"]
integrations: ["Tenable"]
date_added: 2026-09-09
contribution_agreement_date: 2026-09-09T00:00:00Z
compatible_platforms: ["Claude Code"]
invocation: "Say things like \"trigger a patch job for this CVE,\" \"patch these hosts and tell me when it's done,\" or \"did the patch job finish before we rescan\" — the skill activates automatically."
last_reviewed: 2026-09-09
works_with_tenable_hexa_mcp: false
---

## What it does

A closed remediation loop — detect a vulnerability, contain the affected host, patch it, verify the fix, release containment — needs a "patch" step, but there is no single standard patch-management API across vendors. This skill defines a small, vendor-neutral MCP tool contract (`trigger_patch_job` / `get_patch_job_status`) and orchestrates against whichever MCP server on the session actually implements it, rather than hardcoding to one patch-management vendor.

This is a community-built skill, not official guidance from Tenable or any patch-management vendor.

**Scope:** triggering and polling a patch job to a pass/fail signal. It does not detect vulnerabilities, does not contain hosts, and does not verify a patch actually applied beyond the TPM's own status reporting — those are the other legs of the loop it's designed to sit inside.

## How it works

Requires an MCP server, already connected to the session, that implements the skill's two-tool contract for your patch management tool (none is bundled). When invoked, it:

1. Looks for `trigger_patch_job`/`get_patch_job_status` among the session's connected MCP tools, without assuming any specific vendor.
2. Confirms the target assets and driving CVE/patch with the user before triggering anything.
3. Triggers the job, then polls it to a terminal status with exponential backoff and a timeout (`scripts/poll_patch_job.py`).
4. Reports a clean pass/fail signal — `complete` only counts as a pass; `failed`, timeout, or any status outside the known vocabulary all fail closed — for a calling workflow to gate a subsequent Tenable rescan on.

Includes `scripts/poll_patch_job.py` and `tests/test_poll_patch_job.py` as a reference implementation and test suite, run against an in-memory fake client rather than a real vendor's API — no TPM MCP server was available to test against while building this skill; see the repository's Known Limitations for what that means in practice.

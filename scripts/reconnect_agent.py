#!/usr/bin/env python3
"""
Containment-release step for this skill's Phase 3. Calls SentinelOne's
Management Console REST API directly — NOT through purple-mcp, which is
read-only and has no reconnect tool. Same direct-REST pattern as the
tenable-sentinelone-attack-path-interruption skill's isolate_agent.py, but
for the reversal action.

Endpoint and body shape (POST /web/api/v2.1/agents/actions/connect,
{"filter": {"ids": [agent_id]}}) were LIVE-VERIFIED once, 2026-07-18, in a
round-trip disconnect/reconnect test against a real SentinelOne tenant
(Jon's own home-lab agent, full ownership — chosen specifically so the test
carried no shared blast radius). Confirmed via the agent's networkStatus
field flipping disconnected -> connected. That is one successful call
against one tenant on one date — SentinelOne's API can and does change
versions, so confirm the exact path, auth header, and body shape against
your tenant's current API reference (https://<your-console>/api-doc/overview)
before relying on this in a new environment. This script defaults to a dry
run and requires --confirm plus the exact agent ID to do anything.

Usage:
    export SENTINELONE_CONSOLE_URL="https://<your-console>.sentinelone.net"
    export SENTINELONE_API_TOKEN="..."
    python3 reconnect_agent.py <agent_id> --reason "patch job <job_id> complete, releasing containment"
    python3 reconnect_agent.py <agent_id> --reason "..." --confirm   # actually calls the API
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def reconnect(console_url, api_token, agent_id):
    url = f"{console_url.rstrip('/')}/web/api/v2.1/agents/actions/connect"
    body = json.dumps({"filter": {"ids": [agent_id]}}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"ApiToken {api_token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("agent_id", help="SentinelOne agent ID to reconnect (from search_inventory_items, not the Tenable asset ID)")
    parser.add_argument("--reason", required=True, help="Why containment is being released — logged and printed, never optional")
    parser.add_argument("--confirm", action="store_true", help="Actually call the API. Without this flag, the script only prints what it would do.")
    args = parser.parse_args()

    console_url = os.environ.get("SENTINELONE_CONSOLE_URL")
    api_token = os.environ.get("SENTINELONE_API_TOKEN")

    print(f"Target agent: {args.agent_id}")
    print(f"Reason: {args.reason}")

    if not args.confirm:
        print("\nDry run only (pass --confirm to actually reconnect). No API call made.")
        sys.exit(0)

    if not console_url or not api_token:
        print("SENTINELONE_CONSOLE_URL and SENTINELONE_API_TOKEN must both be set.", file=sys.stderr)
        sys.exit(1)

    print("\n*** Calling SentinelOne reconnect endpoint — releases network containment. ***")
    try:
        result = reconnect(console_url, api_token, args.agent_id)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"\nFAILED — HTTP {e.code}: {body[:500]}", file=sys.stderr)
        print(
            "Unknown whether the agent was reconnected. The host may still be isolated — "
            "verify its connectivity status directly in the SentinelOne console before "
            "assuming anything, and do not report containment as released.",
            file=sys.stderr,
        )
        sys.exit(1)
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"\nFAILED — network error calling SentinelOne: {e}", file=sys.stderr)
        print(
            "Unknown whether the agent was reconnected. Verify its connectivity status "
            "directly in the SentinelOne console before assuming anything.",
            file=sys.stderr,
        )
        sys.exit(1)
    except ValueError as e:
        print(f"\nFAILED — could not parse SentinelOne's response: {e}", file=sys.stderr)
        print(
            "The API call was sent, but the response was not valid JSON. Verify the "
            "agent's connectivity status directly in the SentinelOne console — do not "
            "assume containment was released.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(json.dumps(result, indent=2))
    print(
        "\nDo not treat this response alone as proof of reconnection. Re-check the "
        "agent's network connectivity status (e.g. via list_inventory_items / "
        "search_inventory_items) before reporting containment as released."
    )


if __name__ == "__main__":
    main()

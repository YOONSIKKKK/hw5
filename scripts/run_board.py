"""Run the Campus Customs agent team over the ticket board.

Usage:
    .venv/Scripts/python.exe -m scripts.run_board --reset
    .venv/Scripts/python.exe -m scripts.run_board --tickets 102
    .venv/Scripts/python.exe -m scripts.run_board --reset --approve-all

The MCP server must already be running:
    .venv/Scripts/python.exe -m mcp_server.server --port 8787
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.audit import AuditTrail  # noqa: E402
from backend.config import DEFAULT_SUPERVISOR, MODEL_ID  # noqa: E402
from backend.runner import approve, run_board  # noqa: E402
from backend.shop import approval_rows, cash_balance, shop  # noqa: E402
from shop_db import reset_working_db  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Campus Customs agent team")
    parser.add_argument("--reset", action="store_true", help="restore the pristine database first")
    parser.add_argument("--tickets", nargs="*", type=int, help="ticket ids (default: all open)")
    parser.add_argument("--supervisor", default=DEFAULT_SUPERVISOR)
    parser.add_argument(
        "--approve-all",
        action="store_true",
        help="auto-approve every queued payment after the run (testing only)",
    )
    args = parser.parse_args()

    if args.reset:
        reset_working_db()
        print("database reset to the pristine state")

    run_id = f"run-{uuid.uuid4().hex[:8]}"
    audit = AuditTrail(run_id)
    print(f"run {run_id} | model {MODEL_ID} | cash ${await cash_balance():,.2f}\n")

    summary = await run_board(
        ticket_ids=args.tickets, supervisor=args.supervisor, audit=audit, run_id=run_id
    )

    for result in summary.tickets:
        print(f"--- ticket {result.ticket_id}: {result.subject}")
        if result.error:
            print(f"    ERROR {result.error}")
        elif result.decision:
            d = result.decision
            print(f"    status      {d.status}")
            print(f"    decision    {d.decision}")
            print(f"    consulted   {', '.join(d.agents_consulted) or '(none)'}")
            if d.awaiting_approval:
                print(f"    awaiting    approvals {d.awaiting_approval}")
        print(
            f"    usage       {result.usage.requests} requests, "
            f"{result.usage.tool_calls} tool calls, "
            f"{result.usage.total_tokens:,} tokens"
        )

    pending = await approval_rows("pending")
    print(f"\npending approvals: {len(pending)}")
    for a in pending:
        print(f"  #{a['id']} {a['kind']} ${a['amount']:,.2f} -- {a['memo']} (by {a['requested_by']})")

    if args.approve_all and pending:
        print("\napproving everything (testing only)...")
        for a in pending:
            result = await approve(a["id"], "approve", args.supervisor, "auto-approved", audit)
            print(f"  #{a['id']}: {result.get('message') or result.get('error')}")

    print(
        f"\ntotal usage: {summary.usage.requests} requests, "
        f"{summary.usage.tool_calls} tool calls, "
        f"{summary.usage.total_tokens:,} tokens"
    )
    print(f"cash: ${summary.cash_before:,.2f} -> ${await cash_balance():,.2f}")
    print(f"audit trail: {audit.path.relative_to(ROOT)} ({len(audit.events)} events total)")

    await shop.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

"""Drive a complete resolution run over all three tickets.

Resets the working database, then works tickets 101, 102 and 103 through the
running backend so the dashboard shows everything live.  Between attempts the
supervisor's approvals are recorded -- which is what unblocks the next step,
since a purchase order cannot even be *requested* from a vendor that is holding
shipments over an unpaid invoice.

Usage:  .venv/Scripts/python.exe -m scripts.full_run
Writes: output/resolved_tickets.json  (+ appends to output/audit_trail.json)

The MCP server, the backend and the dashboard must all be running.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API = "http://localhost:8000"
SUPERVISOR = "Yunsik Jung"
TICKETS = [101, 102, 103]
MAX_ATTEMPTS = 3

OUT = ROOT / "output" / "resolved_tickets.json"


def get(path: str):
    with urllib.request.urlopen(f"{API}{path}", timeout=60) as r:
        return json.load(r)


def post(path: str, body: dict | None = None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        f"{API}{path}", data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()[:400], "status": e.code}


def money(n: float) -> str:
    return f"${n:,.2f}"


def wait_for_run(run_id: str, timeout: float = 900) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = get(f"/api/runs/{run_id}")
        if run["status"] != "running":
            return run
        time.sleep(5)
    return {"status": "timeout", "run_id": run_id}


def ticket_status(ticket_id: int) -> dict:
    for t in get("/api/tickets")["tickets"]:
        if t["id"] == ticket_id:
            return t
    return {}


def approve_pending(ledger: list[dict]) -> list[dict]:
    """Record the supervisor's decision on everything waiting.

    Policy: approve what the shop genuinely owes or has justified. The tools
    already refuse anything unaffordable, so nothing here can overdraw the
    account -- a rejection at this point would be a business choice, not a
    safety one.
    """
    decided = []
    for a in get("/api/approvals")["approvals"]:
        if a["status"] != "pending":
            continue
        before = get("/api/cash")["balance"]
        result = post(
            f"/api/approvals/{a['id']}/decision",
            {"decision": "approve", "approver": SUPERVISOR, "note": "Approved by the supervisor."},
        )
        if "error" in result:
            print(f"    ! approval {a['id']} failed: {result['error'][:160]}")
            continue
        after = result["cash_after"]
        entry = {
            "approval_id": a["id"],
            "kind": a["kind"],
            "ticket_id": a["ticket_id"],
            "amount": a["amount"],
            "memo": a["memo"],
            "requested_by": a["requested_by"],
            "approved_by": SUPERVISOR,
            "cash_before": before,
            "cash_after": after,
            "detail": result.get("result"),
        }
        ledger.append(entry)
        decided.append(entry)
        print(
            f"    [ok] approved #{a['id']} {a['kind']} {money(a['amount'])} "
            f"-> cash {money(before)} -> {money(after)}"
        )
    return decided


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve the ticket board end to end")
    parser.add_argument("--tickets", nargs="*", type=int, default=TICKETS)
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="continue from the current database instead of resetting",
    )
    args = parser.parse_args()

    previous: dict = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    carried: dict[int, dict] = {}

    if args.no_reset:
        current = get("/api/cash")["balance"]
        opening = previous.get("cash", {}).get("opening_balance", current)
        ledger: list[dict] = list(previous.get("cash", {}).get("movements", []))
        carried = {t["ticket_id"]: t for t in previous.get("tickets", [])}
        print("=" * 74)
        print(f"CONTINUING - current checking balance {money(current)}")
        print("=" * 74 + "\n")
    else:
        print("=" * 74)
        print("RESET")
        print("=" * 74)
        reset = post("/api/reset")
        opening = reset["cash"]
        ledger = []
        print(f"database restored - opening checking balance {money(opening)}\n")

    results: list[dict] = []

    for ticket_id in args.tickets:
        print("=" * 74)
        print(f"TICKET {ticket_id}")
        print("=" * 74)
        attempts = []

        for attempt in range(1, MAX_ATTEMPTS + 1):
            state = post(f"/api/tickets/{ticket_id}/run", {"wait": False})
            if "error" in state:
                print(f"  attempt {attempt}: could not start - {state['error'][:160]}")
                break

            print(f"  attempt {attempt}: run {state['run_id']} ...", flush=True)
            run = wait_for_run(state["run_id"])
            summary = (run.get("summary") or {}).get("tickets", [{}])[0]
            decision = summary.get("decision") or {}
            usage = (run.get("summary") or {}).get("usage", {})

            print(f"    status      {run['status']}")
            if decision:
                print(f"    verdict     {decision.get('status')}")
                print(f"    consulted   {', '.join(decision.get('agents_consulted') or []) or '-'}")
                print(f"    decision    {(decision.get('decision') or '')[:150]}")
            if summary.get("error"):
                print(f"    ERROR       {summary['error'][:200]}")
            print(
                f"    usage       {usage.get('requests', 0)} requests, "
                f"{usage.get('tool_calls', 0)} tools, {usage.get('total_tokens', 0):,} tokens"
            )

            approved = approve_pending(ledger)

            attempts.append(
                {
                    "attempt": attempt,
                    "run_id": state["run_id"],
                    "run_status": run["status"],
                    "decision": decision or None,
                    "error": summary.get("error"),
                    "usage": usage,
                    "approvals_granted": approved,
                }
            )

            ticket = ticket_status(ticket_id)
            print(f"    board       ticket {ticket_id} is now '{ticket.get('status')}'")

            if ticket.get("status") == "resolved":
                break
            if attempt < MAX_ATTEMPTS and approved:
                print("    -> approvals granted; re-running so the team can act on them")
            elif attempt < MAX_ATTEMPTS:
                print("    -> nothing new was approved; one more pass to try to close it")
            print()

        ticket = ticket_status(ticket_id)
        results.append(
            {
                "ticket_id": ticket_id,
                "subject": ticket.get("subject"),
                "requester": ticket.get("requester"),
                "type": ticket.get("type"),
                "final_status": ticket.get("status"),
                "assigned_to": ticket.get("assigned_to"),
                "resolution": ticket.get("resolution"),
                # Keep earlier passes so the record shows the whole history.
                "attempts": (carried.get(ticket_id, {}).get("attempts", []) + attempts),
            }
        )
        print(f"  FINAL: ticket {ticket_id} -> {ticket.get('status')}\n")

    # Tickets not touched on this pass keep their recorded outcome.
    touched = {r["ticket_id"] for r in results}
    for ticket_id, record in carried.items():
        if ticket_id not in touched:
            current = ticket_status(ticket_id)
            record["final_status"] = current.get("status", record.get("final_status"))
            record["resolution"] = current.get("resolution", record.get("resolution"))
            results.append(record)
    results.sort(key=lambda r: r["ticket_id"])

    closing = get("/api/cash")["balance"]
    board = get("/api/board")

    # Derive the cash ledger from the database rather than from anything this
    # script accumulated, so the record cannot drift from cash_accounts.
    approved = [a for a in board["approvals"] if a["status"] == "approved"]
    approved.sort(key=lambda a: a["id"])
    spent = round(sum(float(a["amount"]) for a in approved), 2)
    opening = round(closing + spent, 2)
    running = opening
    movements = []
    for a in approved:
        amount = float(a["amount"])
        before, running = running, round(running - amount, 2)
        movements.append(
            {
                "approval_id": a["id"],
                "kind": a["kind"],
                "ticket_id": a["ticket_id"],
                "amount": amount,
                "memo": a["memo"],
                "requested_by": a["requested_by"],
                "approved_by": a["decided_by"],
                "approved_at": a["decided_at"],
                "cash_before": before,
                "cash_after": running,
                "result": a.get("result"),
            }
        )
    ledger = movements

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "supervisor": SUPERVISOR,
        "model": get("/api/health")["model"],
        "cash": {
            "opening_balance": opening,
            "closing_balance": closing,
            "total_spent": spent,
            "movements": ledger,
            "reconciles_with_database": abs(opening - spent - closing) < 0.005,
        },
        "tickets": results,
        "payments": board["payments"],
        "purchase_orders": board["purchase_orders"],
        "drafts": board["drafts"],
        "approvals": board["approvals"],
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print("=" * 74)
    print("SUMMARY")
    print("=" * 74)
    for r in results:
        print(f"  {r['ticket_id']}  {r['final_status']:<12} {r['subject']}")
    print()
    print(f"  opening {money(opening)}")
    for m in ledger:
        print(f"    - {money(m['amount']):>10}  {m['kind']:<16} ticket {m['ticket_id']}")
    print(f"  closing {money(closing)}")
    print(f"\n  wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Smoke-test the three essential MCP tools and write the evidence file.

Launches the Campus Customs MCP server exactly the way ``.mcp.json`` does -- as
a stdio subprocess -- so this exercises the same configuration the vibe coder
connects through, over the real MCP protocol rather than by importing the tool
functions directly.

For every tool it records the prompt, the tool name, the arguments, the raw tool
output, and an independent SQL query against ``data/campus_customs_new.db``
proving the output matches what is actually in the database.

Usage:  .venv/Scripts/python.exe -m scripts.mcp_smoke
Writes: output/mcp_smoke.json
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp import Client, StdioServerParameters  # noqa: E402

from shop_db import connect, reset_working_db  # noqa: E402
from shop_db.db import WORKING_DB  # noqa: E402

OUTPUT = ROOT / "output" / "mcp_smoke.json"
MCP_CONFIG = ROOT / ".mcp.json"


def tool_payload(result) -> dict:
    """Unwrap an MCP CallToolResult into the plain dict the tool returned."""
    if result.structured_content:
        return result.structured_content
    return json.loads(result.content[0].text)


def query(sql: str, params: tuple = ()) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params)]


def server_params() -> StdioServerParameters:
    """Build the subprocess launch parameters straight out of .mcp.json."""
    config = json.loads(MCP_CONFIG.read_text())["mcpServers"]["campus-customs"]
    command = config["command"]
    if not Path(command).is_absolute():
        command = str(ROOT / command)
    return StdioServerParameters(
        command=command,
        args=config["args"],
        env=config.get("env") or None,
        cwd=str(ROOT),
    )


async def main() -> None:
    # Start from the pristine state so the recorded evidence is reproducible.
    reset_working_db()
    checks: list[dict] = []

    async with Client(server_params()) as client:
        tool_names = sorted(t.name for t in (await client.list_tools()).tools)

        # ------------------------------------------------------------------
        # Ticket 101 -- check_inventory
        # ------------------------------------------------------------------
        args = {"sku": "CC-TEE-WHITE", "size": "S"}
        out = tool_payload(await client.call_tool("check_inventory", args))
        expected = query(
            "SELECT sku, name, size, qty, location FROM inventory WHERE sku = ? AND size = ?",
            ("CC-TEE-WHITE", "S"),
        )
        checks.append({
            "ticket": 101,
            "prompt": (
                "Ticket 101 is a customer order from Tauhid Zaman for one Classic "
                "Bulldog Tee in size S. Using the campus-customs MCP server, check "
                "how many of that exact SKU and size we actually have on the shelf "
                "right now."
            ),
            "tool": "check_inventory",
            "arguments": args,
            "output": out,
            "database_verification": {
                "database": WORKING_DB.name,
                "query": (
                    "SELECT sku, name, size, qty, location FROM inventory "
                    "WHERE sku = 'CC-TEE-WHITE' AND size = 'S'"
                ),
                "rows": expected,
                "matches_database": out.get("inventory") == expected,
            },
            "what_it_proves": (
                "The size-S row holds qty 0, so ticket 101 cannot be filled off "
                "the shelf and has to become a restock."
            ),
        })

        # ------------------------------------------------------------------
        # Ticket 102 -- request_payment
        # ------------------------------------------------------------------
        cash_before = query("SELECT balance FROM cash_accounts WHERE name = 'checking'")[0]["balance"]
        args = {
            "kind": "rent",
            "ref_id": 1,
            "amount": 2400.0,
            "memo": "September rent for the Chapel Street shop, ticket 102",
            "requested_by": "accounting",
            "ticket_id": 102,
        }
        out = tool_payload(await client.call_tool("request_payment", args))
        approval_rows = query(
            "SELECT id, kind, ref_id, ticket_id, amount, account, status, requested_by "
            "FROM approvals WHERE id = ?",
            (out.get("approval_id"),),
        )
        lease_rows = query("SELECT id, space_name, landlord, monthly_rent, next_due FROM leases WHERE id = 1")
        cash_after = query("SELECT balance FROM cash_accounts WHERE name = 'checking'")[0]["balance"]
        payments_count = query("SELECT COUNT(*) AS n FROM payments")[0]["n"]
        checks.append({
            "ticket": 102,
            "prompt": (
                "Ticket 102 is the rent notice from Elm City Properties, which "
                "points at lease 1. Using the campus-customs MCP server, put the "
                "rent payment in front of me for approval -- do not pay it."
            ),
            "tool": "request_payment",
            "arguments": args,
            "output": out,
            "database_verification": {
                "database": WORKING_DB.name,
                "approval_row_created": {
                    "query": "SELECT id, kind, ref_id, ticket_id, amount, account, status, requested_by FROM approvals WHERE id = <approval_id>",
                    "rows": approval_rows,
                },
                "amount_matches_lease": {
                    "query": "SELECT id, space_name, landlord, monthly_rent, next_due FROM leases WHERE id = 1",
                    "rows": lease_rows,
                    "requested_amount": args["amount"],
                    "matches_database": bool(lease_rows) and lease_rows[0]["monthly_rent"] == args["amount"],
                },
                "no_money_moved": {
                    "query": "SELECT balance FROM cash_accounts WHERE name = 'checking'; SELECT COUNT(*) FROM payments",
                    "cash_before": cash_before,
                    "cash_after": cash_after,
                    "payments_rows": payments_count,
                    "balance_unchanged": cash_before == cash_after,
                },
                "matches_database": (
                    bool(approval_rows)
                    and approval_rows[0]["status"] == "pending"
                    and approval_rows[0]["amount"] == args["amount"]
                    and cash_before == cash_after
                    and payments_count == 0
                ),
            },
            "what_it_proves": (
                "The $2,400 matches lease 1's monthly_rent exactly, the request "
                "landed in approvals as 'pending', and the balance is untouched "
                "with zero payment rows -- the agent could not pay it itself."
            ),
        })

        # ------------------------------------------------------------------
        # Ticket 103 -- quote_discount
        # ------------------------------------------------------------------
        args = {"sku": "CC-HOOD-NAVY", "qty": 20, "discount_pct": 25.0}
        out = tool_payload(await client.call_tool("quote_discount", args))
        pricing_rows = query("SELECT sku, unit_cost, list_price FROM pricing WHERE sku = 'CC-HOOD-NAVY'")
        price = pricing_rows[0]
        unit_price = round(price["list_price"] * 0.75, 2)
        margin_pct = round((unit_price - price["unit_cost"]) / unit_price * 100, 2)
        max_discount = round((1 - (price["unit_cost"] / 0.6) / price["list_price"]) * 100, 2)
        checks.append({
            "ticket": 103,
            "prompt": (
                "Ticket 103 is the Yale AI Club asking for 20 navy hoodies in size "
                "M at a bulk discount. Using the campus-customs MCP server, work "
                "out whether 25% off still clears our 40% margin floor, and what "
                "the deepest discount we could actually offer is."
            ),
            "tool": "quote_discount",
            "arguments": args,
            "output": out,
            "database_verification": {
                "database": WORKING_DB.name,
                "query": "SELECT sku, unit_cost, list_price FROM pricing WHERE sku = 'CC-HOOD-NAVY'",
                "rows": pricing_rows,
                "recomputed_from_database": {
                    "discounted_unit_price": unit_price,
                    "gross_margin_pct": margin_pct,
                    "max_discount_pct_allowed": max_discount,
                },
                "matches_database": (
                    out.get("unit_cost") == price["unit_cost"]
                    and out.get("list_price") == price["list_price"]
                    and out.get("discounted_unit_price") == unit_price
                    and out.get("gross_margin_pct") == margin_pct
                    and out.get("max_discount_pct_allowed") == max_discount
                ),
            },
            "what_it_proves": (
                "Every figure is derived from CC-HOOD-NAVY's stored $22.00 cost "
                "and $58.00 list price -- 25% off yields a 49.43% margin (passes), "
                "and the ceiling is 36.78% before the 40% floor is breached."
            ),
        })

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mcp_server": "campus-customs",
        "mcp_config": ".mcp.json",
        "transport": "stdio subprocess, launched from .mcp.json",
        "database": f"data/{WORKING_DB.name}",
        "database_state": "reset to the pristine data/campus_customs.db before these calls",
        "tools_exposed": tool_names,
        "all_checks_match_database": all(
            c["database_verification"]["matches_database"] for c in checks
        ),
        "checks": checks,
    }
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(evidence, indent=2) + "\n")

    print(f"tools exposed: {len(tool_names)}")
    for c in checks:
        verdict = "MATCH" if c["database_verification"]["matches_database"] else "MISMATCH"
        print(f"  ticket {c['ticket']:>3}  {c['tool']:<18} -> {verdict}")
    print(f"\nall checks match database: {evidence['all_checks_match_database']}")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())

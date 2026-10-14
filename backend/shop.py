"""The backend's only window onto the shop -- and it is the MCP server.

Nothing here opens the database.  Every fact the backend shows in the dashboard,
and the one write it performs (recording a human's approval decision), goes
through the same MCP tools the agents use.  There is deliberately no second
data path.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp import Client

from backend.config import MCP_URL


class ShopClient:
    """A reusable MCP client for the Campus Customs server."""

    def __init__(self, url: str | None = None) -> None:
        self.url = url or MCP_URL
        self._client: Client | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._client is None:
            client = Client(self.url)
            await client.__aenter__()
            self._client = client

    async def close(self) -> None:
        if self._client is not None:
            client, self._client = self._client, None
            await client.__aexit__(None, None, None)

    async def call(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call an MCP tool and return the plain dict the tool produced."""
        if self._client is not None:
            async with self._lock:
                result = await self._client.call_tool(tool, arguments or {})
        else:
            # One-shot connection, used by scripts that have no app lifespan.
            async with Client(self.url) as client:
                result = await client.call_tool(tool, arguments or {})
        if result.structured_content:
            return result.structured_content
        if result.content:
            return json.loads(result.content[0].text)
        return {}


shop = ShopClient()


# --------------------------------------------------------------------------
# Reads used by the runner and the dashboard
# --------------------------------------------------------------------------
async def overview() -> dict[str, Any]:
    return await shop.call("get_shop_overview")


async def open_tickets() -> list[dict[str, Any]]:
    return (await overview()).get("open_tickets", [])


async def all_tickets() -> list[dict[str, Any]]:
    return (await shop.call("list_tickets")).get("tickets", [])


async def ticket_row(ticket_id: int) -> dict[str, Any] | None:
    result = await shop.call("get_ticket", {"ticket_id": ticket_id})
    return result.get("ticket") if result.get("ok") else None


async def cash_balance() -> float:
    return float((await shop.call("get_cash")).get("balance", 0.0))


async def approval_rows(status: str | None = None) -> list[dict[str, Any]]:
    args = {"status": status} if status else {}
    return (await shop.call("list_approvals", args)).get("approvals", [])


async def inventory_rows() -> list[dict[str, Any]]:
    return (await shop.call("check_inventory")).get("inventory", [])


async def invoice_rows() -> list[dict[str, Any]]:
    return (await shop.call("list_invoices")).get("invoices", [])


async def lease_rows() -> list[dict[str, Any]]:
    return (await shop.call("list_leases")).get("leases", [])


async def payment_rows() -> list[dict[str, Any]]:
    return (await shop.call("list_payments")).get("payments", [])


async def purchase_order_rows() -> list[dict[str, Any]]:
    return (await shop.call("list_purchase_orders")).get("purchase_orders", [])


async def draft_rows() -> list[dict[str, Any]]:
    return (await shop.call("list_drafts")).get("drafts", [])


async def board_notes() -> list[dict[str, Any]]:
    return (await shop.call("list_board_notes")).get("notes", [])


async def payment_plan() -> dict[str, Any]:
    return await shop.call("get_payment_plan")


# --------------------------------------------------------------------------
# The one write the backend performs, and only on a human's behalf
# --------------------------------------------------------------------------
async def resolve_approval(
    approval_id: int, decision: str, approver: str, note: str | None = None
) -> dict[str, Any]:
    """Execute or reject a queued payment. Agents cannot reach this tool."""
    return await shop.call(
        "supervisor_resolve_approval",
        {
            "approval_id": approval_id,
            "decision": decision,
            "approver": approver,
            "note": note,
        },
    )

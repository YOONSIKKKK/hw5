"""Campus Customs MCP server.

Exposes the shop's database as MCP tools.  This server is the only component
that writes to ``data/campus_customs_new.db``; the agent backend reaches the
shop exclusively through these tools.

Safety rules baked into the tools themselves (not just the prompts):

* ``request_payment`` / ``request_purchase_order`` only ever create a PENDING
  approval.  Money moves in ``supervisor_resolve_approval``, which the backend
  calls on behalf of a human and which agents are never allowed to call.
* Every money path re-checks the cash floor, so the balance cannot go negative.
* ``request_purchase_order`` refuses a vendor that has an unpaid invoice.
* ``draft_message`` writes to the board and can never send anything.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from mcp_server.policies import (  # noqa: E402
    CASH_ACCOUNT,
    LOW_STOCK_THRESHOLD,
    MIN_GROSS_MARGIN_PCT,
    POLICIES,
)
from shop_db import connect, ensure_working_db, one, rows, shop_today  # noqa: E402
from shop_db.db import utc_now  # noqa: E402

mcp = MCPServer(
    name="campus-customs",
    instructions=(
        "Tools for running the Campus Customs store: tickets, inventory, "
        "pricing, vendors, leases, cash, invoices and message drafts. "
        "Payments and purchase orders can only be requested; a human approves."
    ),
    version="1.0.0",
)

PAYMENT_KINDS = ("invoice", "rent")

# Agents must never call this one; the backend blocks it and only invokes it
# itself once a human has clicked approve or deny in the dashboard.
SUPERVISOR_ONLY_TOOLS = {"supervisor_resolve_approval"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _ok(**data: Any) -> dict[str, Any]:
    return {"ok": True, **data}


def _err(message: str, **data: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, **data}


def _days_in_month(year: int, month: int) -> int:
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    return [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]


def _add_months(iso_day: str, months: int = 1) -> str:
    d = date.fromisoformat(iso_day)
    index = d.month - 1 + months
    year = d.year + index // 12
    month = index % 12 + 1
    return date(year, month, min(d.day, _days_in_month(year, month))).isoformat()


def _add_days(day: date, n: int) -> str:
    return date.fromordinal(day.toordinal() + n).isoformat()


def _cash(conn) -> float:
    row = one(conn, "SELECT balance FROM cash_accounts WHERE name = ?", (CASH_ACCOUNT,))
    return float(row["balance"]) if row else 0.0


def _vendor_open_invoices(conn, vendor_id: int) -> list[dict[str, Any]]:
    return rows(
        conn,
        "SELECT id, amount, due_date, status, description FROM invoices "
        "WHERE vendor_id = ? AND status != 'paid' ORDER BY due_date",
        (vendor_id,),
    )


def _touch_ticket(conn, ticket_id: int | None) -> None:
    if ticket_id is not None:
        conn.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (utc_now(), ticket_id))


# --------------------------------------------------------------------------
# orientation
# --------------------------------------------------------------------------
@mcp.tool(description="Shop policies -- the rules every agent must follow.")
def get_policies() -> dict[str, Any]:
    return _ok(policies=POLICIES, min_gross_margin_pct=MIN_GROSS_MARGIN_PCT)


@mcp.tool(
    description=(
        "One-shot snapshot of the shop: today's date, cash, open tickets, low "
        "stock, unpaid invoices, upcoming rent and pending approvals. Start here."
    )
)
def get_shop_overview() -> dict[str, Any]:
    with connect() as conn:
        today = shop_today(conn)
        desk = one(conn, "SELECT date_today, notes FROM desk LIMIT 1") or {}
        open_invoices = rows(
            conn,
            "SELECT i.id, i.vendor_id, v.name AS vendor, i.amount, i.due_date, "
            "i.status, i.description FROM invoices i JOIN vendors v ON v.id = i.vendor_id "
            "WHERE i.status != 'paid' ORDER BY i.due_date",
        )
        for inv in open_invoices:
            inv["days_overdue"] = (today - date.fromisoformat(inv["due_date"])).days
        leases = rows(
            conn, "SELECT id, space_name, landlord, monthly_rent, next_due FROM leases"
        )
        for lease in leases:
            lease["days_until_due"] = (date.fromisoformat(lease["next_due"]) - today).days
        return _ok(
            date_today=desk.get("date_today"),
            desk_notes=desk.get("notes"),
            cash_balance=_cash(conn),
            open_tickets=rows(
                conn,
                "SELECT id, type, requester, subject, status, assigned_to FROM tickets "
                "WHERE status NOT IN ('resolved', 'closed') ORDER BY id",
            ),
            low_stock=rows(
                conn,
                "SELECT sku, name, size, qty FROM inventory WHERE qty <= ? ORDER BY qty, sku",
                (LOW_STOCK_THRESHOLD,),
            ),
            unpaid_invoices=open_invoices,
            leases=leases,
            pending_approvals=rows(
                conn,
                "SELECT id, kind, amount, memo, requested_by FROM approvals "
                "WHERE status = 'pending' ORDER BY id",
            ),
        )


# --------------------------------------------------------------------------
# tickets
# --------------------------------------------------------------------------
@mcp.tool(description="List tickets on the board, optionally filtered by status.")
def list_tickets(status: str | None = None) -> dict[str, Any]:
    with connect() as conn:
        sql = "SELECT * FROM tickets"
        params: tuple = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        return _ok(tickets=rows(conn, sql + " ORDER BY id", params))


@mcp.tool(description="Full detail for one ticket, including any linked invoice, lease or stock.")
def get_ticket(ticket_id: int) -> dict[str, Any]:
    with connect() as conn:
        ticket = one(conn, "SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        if not ticket:
            return _err(f"No ticket with id {ticket_id}.")
        extra: dict[str, Any] = {}
        if ticket.get("invoice_id"):
            extra["invoice"] = one(
                conn, "SELECT * FROM invoices WHERE id = ?", (ticket["invoice_id"],)
            )
        if ticket.get("lease_id"):
            extra["lease"] = one(conn, "SELECT * FROM leases WHERE id = ?", (ticket["lease_id"],))
        if ticket.get("sku"):
            extra["stock"] = rows(conn, "SELECT * FROM inventory WHERE sku = ?", (ticket["sku"],))
            extra["pricing"] = one(conn, "SELECT * FROM pricing WHERE sku = ?", (ticket["sku"],))
        return _ok(ticket=ticket, **extra)


@mcp.tool(description="Assign a ticket to an agent on the team.")
def assign_ticket(ticket_id: int, agent: str) -> dict[str, Any]:
    with connect() as conn:
        if not one(conn, "SELECT id FROM tickets WHERE id = ?", (ticket_id,)):
            return _err(f"No ticket with id {ticket_id}.")
        conn.execute(
            "UPDATE tickets SET assigned_to = ?, updated_at = ?, status = CASE WHEN "
            "status = 'open' THEN 'in_progress' ELSE status END WHERE id = ?",
            (agent, utc_now(), ticket_id),
        )
        conn.commit()
        return _ok(ticket=one(conn, "SELECT * FROM tickets WHERE id = ?", (ticket_id,)))


@mcp.tool(
    description=(
        "Update a ticket's status and record how it was resolved. Valid statuses: "
        "open, in_progress, blocked, resolved."
    )
)
def update_ticket(
    ticket_id: int,
    status: str | None = None,
    resolution: str | None = None,
    append_note: str | None = None,
) -> dict[str, Any]:
    valid = {"open", "in_progress", "blocked", "resolved"}
    if status and status not in valid:
        return _err(f"Invalid status {status!r}. Use one of: {', '.join(sorted(valid))}.")
    with connect() as conn:
        ticket = one(conn, "SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        if not ticket:
            return _err(f"No ticket with id {ticket_id}.")
        if status:
            conn.execute("UPDATE tickets SET status = ? WHERE id = ?", (status, ticket_id))
        if resolution:
            conn.execute("UPDATE tickets SET resolution = ? WHERE id = ?", (resolution, ticket_id))
        if append_note:
            merged = f"{ticket['notes'] or ''}\n{append_note}".strip()
            conn.execute("UPDATE tickets SET notes = ? WHERE id = ?", (merged, ticket_id))
        _touch_ticket(conn, ticket_id)
        conn.commit()
        return _ok(ticket=one(conn, "SELECT * FROM tickets WHERE id = ?", (ticket_id,)))


# --------------------------------------------------------------------------
# inventory
# --------------------------------------------------------------------------
@mcp.tool(description="Stock on hand, optionally narrowed to a SKU and/or size.")
def check_inventory(sku: str | None = None, size: str | None = None) -> dict[str, Any]:
    clauses, params = [], []
    if sku:
        clauses.append("sku = ?")
        params.append(sku)
    if size:
        clauses.append("size = ?")
        params.append(size)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as conn:
        return _ok(
            inventory=rows(conn, f"SELECT * FROM inventory{where} ORDER BY sku, size", tuple(params))
        )


@mcp.tool(description="Every SKU/size at or below the low-stock threshold.")
def low_stock_report(threshold: int = LOW_STOCK_THRESHOLD) -> dict[str, Any]:
    with connect() as conn:
        shortages = rows(
            conn,
            "SELECT i.sku, i.name, i.size, i.qty, p.unit_cost FROM inventory i "
            "LEFT JOIN pricing p ON p.sku = i.sku WHERE i.qty <= ? ORDER BY i.qty, i.sku",
            (threshold,),
        )
        return _ok(threshold=threshold, shortages=shortages)


@mcp.tool(
    description=(
        "Pull stock off the shelf for a customer order. Fails with the exact "
        "shortfall if there is not enough on hand; never drives stock negative."
    )
)
def reserve_stock(sku: str, size: str, qty: int, ticket_id: int | None = None) -> dict[str, Any]:
    if qty <= 0:
        return _err("Quantity must be positive.")
    with connect() as conn:
        item = one(conn, "SELECT * FROM inventory WHERE sku = ? AND size = ?", (sku, size))
        if not item:
            return _err(f"No inventory record for {sku} size {size}.")
        if item["qty"] < qty:
            return _err(
                f"Insufficient stock: {item['qty']} on hand, {qty} requested.",
                on_hand=item["qty"],
                requested=qty,
                shortfall=qty - item["qty"],
            )
        conn.execute(
            "UPDATE inventory SET qty = qty - ? WHERE sku = ? AND size = ?", (qty, sku, size)
        )
        _touch_ticket(conn, ticket_id)
        conn.commit()
        return _ok(
            sku=sku,
            size=size,
            reserved=qty,
            remaining=item["qty"] - qty,
            ticket_id=ticket_id,
        )


# --------------------------------------------------------------------------
# pricing
# --------------------------------------------------------------------------
@mcp.tool(description="Unit cost and list price, optionally for a single SKU.")
def get_pricing(sku: str | None = None) -> dict[str, Any]:
    with connect() as conn:
        if sku:
            row = one(conn, "SELECT * FROM pricing WHERE sku = ?", (sku,))
            if not row:
                return _err(f"No pricing for {sku}.")
            return _ok(pricing=[row])
        return _ok(pricing=rows(conn, "SELECT * FROM pricing ORDER BY sku"))


@mcp.tool(
    description=(
        "Do the margin math on a proposed bulk discount: discounted unit price, "
        "gross margin, order totals, whether it clears the margin policy, and the "
        "largest discount that still would."
    )
)
def quote_discount(sku: str, qty: int, discount_pct: float) -> dict[str, Any]:
    if qty <= 0:
        return _err("Quantity must be positive.")
    if not 0 <= discount_pct < 100:
        return _err("Discount percent must be between 0 and 100.")
    with connect() as conn:
        price = one(conn, "SELECT * FROM pricing WHERE sku = ?", (sku,))
        if not price:
            return _err(f"No pricing for {sku}.")
    unit_cost = float(price["unit_cost"])
    list_price = float(price["list_price"])
    unit_price = round(list_price * (1 - discount_pct / 100), 2)
    margin_per_unit = round(unit_price - unit_cost, 2)
    margin_pct = round(margin_per_unit / unit_price * 100, 2) if unit_price else -100.0
    floor_price = unit_cost / (1 - MIN_GROSS_MARGIN_PCT / 100)
    max_discount_pct = round(max(0.0, (1 - floor_price / list_price) * 100), 2)
    return _ok(
        sku=sku,
        qty=qty,
        list_price=list_price,
        unit_cost=unit_cost,
        discount_pct=discount_pct,
        discounted_unit_price=unit_price,
        margin_per_unit=margin_per_unit,
        gross_margin_pct=margin_pct,
        order_revenue=round(unit_price * qty, 2),
        order_cost=round(unit_cost * qty, 2),
        order_profit=round(margin_per_unit * qty, 2),
        min_gross_margin_pct=MIN_GROSS_MARGIN_PCT,
        meets_margin_policy=margin_pct >= MIN_GROSS_MARGIN_PCT,
        max_discount_pct_allowed=max_discount_pct,
        price_floor=round(floor_price, 2),
    )


# --------------------------------------------------------------------------
# vendors
# --------------------------------------------------------------------------
@mcp.tool(description="List vendors, optionally filtered by a specialty keyword.")
def list_vendors(specialty: str | None = None) -> dict[str, Any]:
    with connect() as conn:
        if specialty:
            return _ok(
                vendors=rows(
                    conn,
                    "SELECT * FROM vendors WHERE specialty LIKE ? ORDER BY id",
                    (f"%{specialty}%",),
                )
            )
        return _ok(vendors=rows(conn, "SELECT * FROM vendors ORDER BY id"))


@mcp.tool(
    description=(
        "Whether a vendor will ship right now. Reports lead time, any unpaid "
        "invoices that put the vendor on hold, and the earliest delivery date."
    )
)
def get_vendor_status(vendor_id: int) -> dict[str, Any]:
    with connect() as conn:
        vendor = one(conn, "SELECT * FROM vendors WHERE id = ?", (vendor_id,))
        if not vendor:
            return _err(f"No vendor with id {vendor_id}.")
        unpaid = _vendor_open_invoices(conn, vendor_id)
        today = shop_today(conn)
        can_ship = not unpaid
        return _ok(
            vendor=vendor,
            can_ship=can_ship,
            blocked_reason=(
                None
                if can_ship
                else (
                    f"{vendor['name']} is holding shipments until "
                    f"{len(unpaid)} unpaid invoice(s) totalling "
                    f"${sum(i['amount'] for i in unpaid):,.2f} are settled."
                )
            ),
            unpaid_invoices=unpaid,
            lead_days=vendor["lead_days"],
            earliest_delivery=_add_days(today, vendor["lead_days"]) if can_ship else None,
        )


# --------------------------------------------------------------------------
# facilities
# --------------------------------------------------------------------------
@mcp.tool(description="All leases with rent, next due date and days until due.")
def list_leases() -> dict[str, Any]:
    with connect() as conn:
        today = shop_today(conn)
        leases = rows(conn, "SELECT * FROM leases ORDER BY id")
        for lease in leases:
            due = date.fromisoformat(lease["next_due"])
            lease["days_until_due"] = (due - today).days
            lease["is_overdue"] = due < today
        return _ok(leases=leases, date_today=today.isoformat())


# --------------------------------------------------------------------------
# money -- read side
# --------------------------------------------------------------------------
@mcp.tool(description="Current cash balance and the committed, not-yet-approved outflow.")
def get_cash() -> dict[str, Any]:
    with connect() as conn:
        pending = (
            one(conn, "SELECT COALESCE(SUM(amount), 0) AS total FROM approvals WHERE status = 'pending'")
            or {"total": 0.0}
        )
        balance = _cash(conn)
        return _ok(
            account=CASH_ACCOUNT,
            balance=balance,
            pending_approval_total=round(float(pending["total"]), 2),
            uncommitted=round(balance - float(pending["total"]), 2),
        )


@mcp.tool(description="Invoices owed to vendors, optionally filtered by status.")
def list_invoices(status: str | None = None) -> dict[str, Any]:
    with connect() as conn:
        today = shop_today(conn)
        sql = (
            "SELECT i.*, v.name AS vendor FROM invoices i "
            "JOIN vendors v ON v.id = i.vendor_id"
        )
        params: tuple = ()
        if status:
            sql += " WHERE i.status = ?"
            params = (status,)
        invoices = rows(conn, sql + " ORDER BY i.due_date", params)
        for inv in invoices:
            inv["days_overdue"] = (today - date.fromisoformat(inv["due_date"])).days
        return _ok(invoices=invoices)


@mcp.tool(description="Payments already executed, with who approved each one.")
def list_payments() -> dict[str, Any]:
    with connect() as conn:
        return _ok(payments=rows(conn, "SELECT * FROM payments ORDER BY id"))


@mcp.tool(description="Purchase orders placed with vendors and their expected arrival dates.")
def list_purchase_orders() -> dict[str, Any]:
    with connect() as conn:
        return _ok(
            purchase_orders=rows(
                conn,
                "SELECT po.*, v.name AS vendor FROM purchase_orders po "
                "JOIN vendors v ON v.id = po.vendor_id ORDER BY po.id",
            )
        )


@mcp.tool(description="Approval requests, optionally filtered by status (pending/approved/denied/failed).")
def list_approvals(status: str | None = None) -> dict[str, Any]:
    with connect() as conn:
        sql = "SELECT * FROM approvals"
        params: tuple = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        return _ok(approvals=rows(conn, sql + " ORDER BY id", params))


@mcp.tool(description="Look up a single approval request and the human's decision on it.")
def get_approval(approval_id: int) -> dict[str, Any]:
    with connect() as conn:
        approval = one(conn, "SELECT * FROM approvals WHERE id = ?", (approval_id,))
        if not approval:
            return _err(f"No approval with id {approval_id}.")
        return _ok(approval=approval)


# --------------------------------------------------------------------------
# money -- request side (never executes)
# --------------------------------------------------------------------------
def _create_approval(
    conn,
    *,
    kind: str,
    ref_id: int | None,
    ticket_id: int | None,
    amount: float,
    memo: str,
    requested_by: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a pending approval, reusing an identical one that is still open."""
    existing = one(
        conn,
        "SELECT * FROM approvals WHERE kind = ? AND IFNULL(ref_id, -1) = IFNULL(?, -1) "
        "AND status = 'pending'",
        (kind, ref_id),
    )
    if existing:
        return existing
    cursor = conn.execute(
        "INSERT INTO approvals (kind, ref_id, ticket_id, amount, account, memo, payload, "
        "status, requested_by, requested_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
        (
            kind,
            ref_id,
            ticket_id,
            round(float(amount), 2),
            CASH_ACCOUNT,
            memo,
            json.dumps(payload or {}),
            requested_by,
            utc_now(),
        ),
    )
    conn.commit()
    return one(conn, "SELECT * FROM approvals WHERE id = ?", (cursor.lastrowid,))


@mcp.tool(
    description=(
        "Request a payment. Kind is 'invoice' (ref_id = invoice id) or 'rent' "
        "(ref_id = lease id). This NEVER moves money -- it queues the payment for "
        "the human supervisor and is rejected outright if cash is insufficient."
    )
)
def request_payment(
    kind: str,
    ref_id: int,
    amount: float,
    memo: str,
    requested_by: str,
    ticket_id: int | None = None,
) -> dict[str, Any]:
    if kind not in PAYMENT_KINDS:
        return _err(f"Invalid payment kind {kind!r}. Use one of: {', '.join(PAYMENT_KINDS)}.")
    if amount <= 0:
        return _err("Payment amount must be positive.")
    amount = round(float(amount), 2)

    with connect() as conn:
        balance = _cash(conn)
        if amount > balance:
            return _err(
                f"Insufficient cash: balance is ${balance:,.2f} but the payment is "
                f"${amount:,.2f}. The shop cannot go below zero.",
                balance=balance,
                requested=amount,
                shortfall=round(amount - balance, 2),
            )

        if kind == "invoice":
            invoice = one(conn, "SELECT * FROM invoices WHERE id = ?", (ref_id,))
            if not invoice:
                return _err(f"No invoice with id {ref_id}.")
            if invoice["status"] == "paid":
                return _err(f"Invoice {ref_id} is already paid.", invoice=invoice)
            if abs(amount - float(invoice["amount"])) > 0.005:
                return _err(
                    f"Amount ${amount:,.2f} does not match invoice {ref_id} "
                    f"(${invoice['amount']:,.2f}).",
                    invoice=invoice,
                )
            target = f"invoice {ref_id}"
        else:
            lease = one(conn, "SELECT * FROM leases WHERE id = ?", (ref_id,))
            if not lease:
                return _err(f"No lease with id {ref_id}.")
            if abs(amount - float(lease["monthly_rent"])) > 0.005:
                return _err(
                    f"Amount ${amount:,.2f} does not match the monthly rent for "
                    f"{lease['space_name']} (${lease['monthly_rent']:,.2f}).",
                    lease=lease,
                )
            target = f"rent for {lease['space_name']}"

        approval = _create_approval(
            conn,
            kind=kind,
            ref_id=ref_id,
            ticket_id=ticket_id,
            amount=amount,
            memo=memo,
            requested_by=requested_by,
        )
        _touch_ticket(conn, ticket_id)
        conn.commit()

    return _ok(
        status="pending_human_approval",
        approval_id=approval["id"],
        message=(
            f"Payment of ${amount:,.2f} for {target} is queued for the human "
            "supervisor. No money has moved. Do not assume it is paid."
        ),
        approval=approval,
    )


@mcp.tool(
    description=(
        "Request a restock purchase order. Refused if the vendor is holding "
        "shipments over an unpaid invoice, or if cash will not cover it. Like "
        "payments, this only queues the order for human approval."
    )
)
def request_purchase_order(
    vendor_id: int,
    sku: str,
    size: str,
    qty: int,
    memo: str,
    requested_by: str,
    ticket_id: int | None = None,
) -> dict[str, Any]:
    if qty <= 0:
        return _err("Quantity must be positive.")

    with connect() as conn:
        vendor = one(conn, "SELECT * FROM vendors WHERE id = ?", (vendor_id,))
        if not vendor:
            return _err(f"No vendor with id {vendor_id}.")

        unpaid = _vendor_open_invoices(conn, vendor_id)
        if unpaid:
            owed = sum(float(i["amount"]) for i in unpaid)
            return _err(
                f"{vendor['name']} will not ship: ${owed:,.2f} in unpaid invoices "
                f"(ids {', '.join(str(i['id']) for i in unpaid)}) must be settled first.",
                vendor=vendor,
                unpaid_invoices=unpaid,
                next_step="Pay the outstanding invoice, then request this PO again.",
            )

        price = one(conn, "SELECT * FROM pricing WHERE sku = ?", (sku,))
        if not price:
            return _err(f"No pricing for {sku}; cannot cost the order.")
        if not one(conn, "SELECT 1 FROM inventory WHERE sku = ? AND size = ?", (sku, size)):
            return _err(f"No inventory record for {sku} size {size}.")

        unit_cost = float(price["unit_cost"])
        total = round(unit_cost * qty, 2)
        balance = _cash(conn)
        if total > balance:
            affordable = int(balance // unit_cost)
            return _err(
                f"Insufficient cash: the order costs ${total:,.2f} but only "
                f"${balance:,.2f} is available.",
                balance=balance,
                order_total=total,
                shortfall=round(total - balance, 2),
                max_affordable_qty=affordable,
            )

        today = shop_today(conn)
        expected = _add_days(today, int(vendor["lead_days"]))
        approval = _create_approval(
            conn,
            kind="purchase_order",
            ref_id=vendor_id,
            ticket_id=ticket_id,
            amount=total,
            memo=memo,
            requested_by=requested_by,
            payload={
                "vendor_id": vendor_id,
                "vendor": vendor["name"],
                "sku": sku,
                "size": size,
                "qty": qty,
                "unit_cost": unit_cost,
                "expected_date": expected,
            },
        )
        _touch_ticket(conn, ticket_id)
        conn.commit()

    return _ok(
        status="pending_human_approval",
        approval_id=approval["id"],
        order_total=total,
        expected_delivery=expected,
        message=(
            f"Purchase order for {qty} x {sku} ({size}) from {vendor['name']} at "
            f"${total:,.2f} is queued for the human supervisor. Nothing is ordered "
            f"or paid yet. If approved, delivery lands {expected}."
        ),
        approval=approval,
    )


# --------------------------------------------------------------------------
# money -- execution (human only)
# --------------------------------------------------------------------------
@mcp.tool(
    description=(
        "Ask the human supervisor to authorise a discount on a bulk order. A "
        "price override is a pricing decision, not a payment, so no money moves "
        "-- but it still needs human sign-off. Refused outright if the discount "
        "would break the minimum gross margin policy."
    )
)
def request_price_override(
    sku: str,
    qty: int,
    discount_pct: float,
    memo: str,
    requested_by: str,
    ticket_id: int | None = None,
) -> dict[str, Any]:
    if qty <= 0:
        return _err("Quantity must be positive.")
    if not 0 <= discount_pct < 100:
        return _err("Discount percent must be between 0 and 100.")

    quote = quote_discount(sku, qty, discount_pct)
    if not quote.get("ok"):
        return quote
    if not quote["meets_margin_policy"]:
        return _err(
            f"A {discount_pct}% discount leaves only "
            f"{quote['gross_margin_pct']}% gross margin, below the "
            f"{MIN_GROSS_MARGIN_PCT:.0f}% floor. The deepest allowed is "
            f"{quote['max_discount_pct_allowed']}%.",
            quote=quote,
        )

    with connect() as conn:
        approval = _create_approval(
            conn,
            kind="price_override",
            ref_id=None,
            ticket_id=ticket_id,
            amount=0.0,  # a discount costs no cash; it forgoes revenue
            memo=memo,
            requested_by=requested_by,
            payload={
                "sku": sku,
                "qty": qty,
                "discount_pct": discount_pct,
                "unit_price": quote["discounted_unit_price"],
                "list_price": quote["list_price"],
                "gross_margin_pct": quote["gross_margin_pct"],
                "order_revenue": quote["order_revenue"],
                "order_profit": quote["order_profit"],
                "max_discount_pct_allowed": quote["max_discount_pct_allowed"],
            },
        )
        _touch_ticket(conn, ticket_id)
        conn.commit()

    return _ok(
        status="pending_human_approval",
        approval_id=approval["id"],
        quote=quote,
        message=(
            f"A {discount_pct}% discount on {qty} x {sku} "
            f"(${quote['discounted_unit_price']:,.2f} each, "
            f"{quote['gross_margin_pct']}% margin) is queued for the human "
            "supervisor. Do not quote it to the customer as final until it is "
            "authorised."
        ),
        approval=approval,
    )


@mcp.tool(
    description=(
        "SUPERVISOR ONLY. Records a human's approve/deny decision and, on "
        "approval, actually moves the money. Agents must never call this."
    )
)
def supervisor_resolve_approval(
    approval_id: int,
    decision: str,
    approver: str,
    note: str | None = None,
) -> dict[str, Any]:
    if decision not in ("approve", "deny"):
        return _err("Decision must be 'approve' or 'deny'.")
    if not approver or not approver.strip():
        return _err("An approver name is required; payments cannot be self-approved.")

    with connect() as conn:
        approval = one(conn, "SELECT * FROM approvals WHERE id = ?", (approval_id,))
        if not approval:
            return _err(f"No approval with id {approval_id}.")
        if approval["status"] != "pending":
            return _err(
                f"Approval {approval_id} was already {approval['status']}.", approval=approval
            )

        if decision == "deny":
            conn.execute(
                "UPDATE approvals SET status = 'denied', decided_by = ?, decided_at = ?, "
                "decision_note = ? WHERE id = ?",
                (approver, utc_now(), note, approval_id),
            )
            conn.commit()
            return _ok(
                executed=False,
                approval=one(conn, "SELECT * FROM approvals WHERE id = ?", (approval_id,)),
                message=f"Approval {approval_id} denied by {approver}. No money moved.",
            )

        # A price override is a pricing decision, not an outflow -- it is
        # authorised without any money changing hands.
        if approval["kind"] == "price_override":
            payload = json.loads(approval["payload"] or "{}")
            result = {"authorised_terms": payload, "cash_moved": 0.0}
            conn.execute(
                "UPDATE approvals SET status = 'approved', decided_by = ?, decided_at = ?, "
                "decision_note = ?, result = ? WHERE id = ?",
                (approver, utc_now(), note, json.dumps(result), approval_id),
            )
            _touch_ticket(conn, approval["ticket_id"])
            conn.commit()
            return _ok(
                executed=True,
                approval=one(conn, "SELECT * FROM approvals WHERE id = ?", (approval_id,)),
                result=result,
                message=(
                    f"{approver} authorised a {payload.get('discount_pct')}% discount on "
                    f"{payload.get('qty')} x {payload.get('sku')} at "
                    f"${payload.get('unit_price', 0):,.2f} each. No cash moved."
                ),
            )

        amount = float(approval["amount"])
        balance = _cash(conn)
        # Re-check at execution time: the balance may have moved since the request.
        if amount > balance:
            failure = (
                f"Cannot execute: ${amount:,.2f} requested but only ${balance:,.2f} "
                "on hand. The balance may never go below zero."
            )
            conn.execute(
                "UPDATE approvals SET status = 'failed', decided_by = ?, decided_at = ?, "
                "decision_note = ?, result = ? WHERE id = ?",
                (approver, utc_now(), note, json.dumps({"error": failure}), approval_id),
            )
            conn.commit()
            return _err(failure, balance=balance, requested=amount)

        today = shop_today(conn).isoformat()
        kind = approval["kind"]
        result: dict[str, Any] = {}

        conn.execute(
            "UPDATE cash_accounts SET balance = balance - ?, date = ? WHERE name = ?",
            (amount, today, CASH_ACCOUNT),
        )
        payment_kind = {"invoice": "invoice", "rent": "rent", "purchase_order": "purchase_order"}[kind]
        cursor = conn.execute(
            "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (payment_kind, approval["ref_id"], amount, CASH_ACCOUNT, today, approver),
        )
        result["payment_id"] = cursor.lastrowid

        if kind == "invoice":
            conn.execute(
                "UPDATE invoices SET status = 'paid' WHERE id = ?", (approval["ref_id"],)
            )
            result["invoice_id"] = approval["ref_id"]
            result["invoice_status"] = "paid"
        elif kind == "rent":
            lease = one(conn, "SELECT * FROM leases WHERE id = ?", (approval["ref_id"],))
            if lease:
                next_due = _add_months(lease["next_due"], 1)
                conn.execute(
                    "UPDATE leases SET next_due = ? WHERE id = ?", (next_due, lease["id"])
                )
                result["lease_id"] = lease["id"]
                result["next_due"] = next_due
        elif kind == "purchase_order":
            payload = json.loads(approval["payload"] or "{}")
            po = conn.execute(
                "INSERT INTO purchase_orders (vendor_id, sku, size, qty, unit_cost, total, "
                "status, expected_date, ticket_id, approval_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'ordered', ?, ?, ?, ?)",
                (
                    payload.get("vendor_id", approval["ref_id"]),
                    payload.get("sku"),
                    payload.get("size"),
                    payload.get("qty"),
                    payload.get("unit_cost"),
                    amount,
                    payload.get("expected_date"),
                    approval["ticket_id"],
                    approval_id,
                    utc_now(),
                ),
            )
            result["purchase_order_id"] = po.lastrowid
            result["expected_date"] = payload.get("expected_date")

        new_balance = _cash(conn)
        result["cash_before"] = balance
        result["cash_after"] = new_balance
        conn.execute(
            "UPDATE approvals SET status = 'approved', decided_by = ?, decided_at = ?, "
            "decision_note = ?, result = ? WHERE id = ?",
            (approver, utc_now(), note, json.dumps(result), approval_id),
        )
        _touch_ticket(conn, approval["ticket_id"])
        conn.commit()

        return _ok(
            executed=True,
            approval=one(conn, "SELECT * FROM approvals WHERE id = ?", (approval_id,)),
            result=result,
            message=(
                f"{approver} approved approval {approval_id}. ${amount:,.2f} paid; "
                f"cash is now ${new_balance:,.2f}."
            ),
        )


# --------------------------------------------------------------------------
# communications -- drafts only
# --------------------------------------------------------------------------
@mcp.tool(
    description=(
        "Write a message DRAFT onto the board for the human to review. Nothing "
        "is ever sent: no real email leaves the shop and no vendor is called."
    )
)
def draft_message(
    ticket_id: int | None,
    recipient: str,
    subject: str,
    body: str,
    author: str,
    channel: str = "email",
) -> dict[str, Any]:
    if channel not in ("email", "board_note", "phone_script"):
        return _err("Channel must be 'email', 'board_note' or 'phone_script'.")
    if not body.strip():
        return _err("Draft body cannot be empty.")
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO drafts (ticket_id, channel, recipient, subject, body, author, "
            "status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'draft', ?)",
            (ticket_id, channel, recipient, subject, body, author, utc_now()),
        )
        _touch_ticket(conn, ticket_id)
        conn.commit()
        draft = one(conn, "SELECT * FROM drafts WHERE id = ?", (cursor.lastrowid,))
    return _ok(
        draft=draft,
        message=f"Draft {draft['id']} saved to the board for {recipient}. NOT SENT.",
    )


@mcp.tool(description="Message drafts sitting on the board, optionally for one ticket.")
def list_drafts(ticket_id: int | None = None) -> dict[str, Any]:
    with connect() as conn:
        if ticket_id is not None:
            return _ok(
                drafts=rows(
                    conn, "SELECT * FROM drafts WHERE ticket_id = ? ORDER BY id", (ticket_id,)
                )
            )
        return _ok(drafts=rows(conn, "SELECT * FROM drafts ORDER BY id"))


@mcp.tool(
    description=(
        "Everything needed to decide a restock in one call: the shortfall for a "
        "SKU/size, what it costs at unit cost, every vendor with its lead time, "
        "whether each one is on hold over an unpaid invoice, the delivery date "
        "each could hit, and whether the shop can currently afford it."
    )
)
def find_restock_options(sku: str, size: str, qty: int) -> dict[str, Any]:
    if qty <= 0:
        return _err("Quantity must be positive.")
    with connect() as conn:
        item = one(conn, "SELECT * FROM inventory WHERE sku = ? AND size = ?", (sku, size))
        if not item:
            return _err(f"No inventory record for {sku} size {size}.")
        price = one(conn, "SELECT * FROM pricing WHERE sku = ?", (sku,))
        if not price:
            return _err(f"No pricing for {sku}.")

        on_hand = int(item["qty"])
        shortfall = max(0, qty - on_hand)
        unit_cost = float(price["unit_cost"])
        restock_cost = round(unit_cost * shortfall, 2)
        balance = _cash(conn)
        today = shop_today(conn)

        options = []
        for vendor in rows(conn, "SELECT * FROM vendors ORDER BY id"):
            unpaid = _vendor_open_invoices(conn, vendor["id"])
            can_ship = not unpaid
            options.append(
                {
                    "vendor_id": vendor["id"],
                    "name": vendor["name"],
                    "specialty": vendor["specialty"],
                    "lead_days": vendor["lead_days"],
                    "can_ship": can_ship,
                    "blocking_invoices": [i["id"] for i in unpaid],
                    "blocking_total": round(sum(float(i["amount"]) for i in unpaid), 2),
                    "earliest_delivery": _add_days(today, int(vendor["lead_days"]))
                    if can_ship
                    else None,
                }
            )

        return _ok(
            sku=sku,
            size=size,
            requested_qty=qty,
            on_hand=on_hand,
            shortfall=shortfall,
            unit_cost=unit_cost,
            restock_cost=restock_cost,
            cash_balance=balance,
            affordable=restock_cost <= balance,
            max_affordable_qty=int(balance // unit_cost) if unit_cost else 0,
            date_today=today.isoformat(),
            vendors=options,
        )


@mcp.tool(
    description=(
        "The shop's full cash picture for prioritising: balance, every unpaid "
        "invoice, every rent payment coming due, what is already queued for "
        "approval, and whether the cash on hand covers all of it."
    )
)
def get_payment_plan() -> dict[str, Any]:
    with connect() as conn:
        today = shop_today(conn)
        balance = _cash(conn)

        obligations: list[dict[str, Any]] = []
        for inv in rows(
            conn,
            "SELECT i.*, v.name AS vendor FROM invoices i JOIN vendors v ON v.id = i.vendor_id "
            "WHERE i.status != 'paid' ORDER BY i.due_date",
        ):
            obligations.append(
                {
                    "kind": "invoice",
                    "ref_id": inv["id"],
                    "payee": inv["vendor"],
                    "amount": float(inv["amount"]),
                    "due_date": inv["due_date"],
                    "days_overdue": (today - date.fromisoformat(inv["due_date"])).days,
                    "description": inv["description"],
                    "blocks_vendor_shipping": True,
                }
            )
        for lease in rows(conn, "SELECT * FROM leases ORDER BY id"):
            obligations.append(
                {
                    "kind": "rent",
                    "ref_id": lease["id"],
                    "payee": lease["landlord"],
                    "amount": float(lease["monthly_rent"]),
                    "due_date": lease["next_due"],
                    "days_until_due": (date.fromisoformat(lease["next_due"]) - today).days,
                    "description": f"Rent for {lease['space_name']}",
                    "blocks_vendor_shipping": False,
                }
            )

        total = round(sum(o["amount"] for o in obligations), 2)
        pending = rows(
            conn,
            "SELECT id, kind, ref_id, amount, memo, requested_by, status FROM approvals "
            "WHERE status = 'pending' ORDER BY id",
        )
        return _ok(
            date_today=today.isoformat(),
            cash_balance=balance,
            obligations=obligations,
            total_obligations=total,
            pending_approvals=pending,
            pending_approval_total=round(sum(float(p["amount"]) for p in pending), 2),
            cash_after_all_obligations=round(balance - total, 2),
            covers_everything=total <= balance,
        )


@mcp.tool(
    description=(
        "Leave a note on the shop board so the human supervisor and the other "
        "agents can see the reasoning behind a decision."
    )
)
def post_board_note(agent: str, note: str, ticket_id: int | None = None) -> dict[str, Any]:
    if not note.strip():
        return _err("Note cannot be empty.")
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO activity_log (run_id, ts, kind, agent, ticket_id, summary, detail) "
            "VALUES (NULL, ?, 'board_note', ?, ?, ?, NULL)",
            (utc_now(), agent, ticket_id, note.strip()),
        )
        _touch_ticket(conn, ticket_id)
        conn.commit()
        return _ok(note_id=cursor.lastrowid, ticket_id=ticket_id, agent=agent)


@mcp.tool(description="Notes posted to the shop board, newest last.")
def list_board_notes(ticket_id: int | None = None) -> dict[str, Any]:
    with connect() as conn:
        if ticket_id is not None:
            return _ok(
                notes=rows(
                    conn,
                    "SELECT * FROM activity_log WHERE kind = 'board_note' AND ticket_id = ? "
                    "ORDER BY id",
                    (ticket_id,),
                )
            )
        return _ok(
            notes=rows(
                conn, "SELECT * FROM activity_log WHERE kind = 'board_note' ORDER BY id"
            )
        )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Campus Customs MCP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--transport", default="streamable-http", choices=["streamable-http", "stdio"])
    args = parser.parse_args()

    ensure_working_db()
    if args.transport == "stdio":
        mcp.run("stdio")
    else:
        import anyio

        anyio.run(
            lambda: mcp.run_streamable_http_async(host=args.host, port=args.port)
        )


if __name__ == "__main__":
    main()

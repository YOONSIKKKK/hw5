# Campus Customs MCP Server

## Purpose

This MCP server is the **only** component allowed to touch the shop's database.
The five agents on the Campus Customs team (Boss, Inventory, Accounting,
Facilities, Customer Service) have no SQL access of their own — everything they
know about stock, prices, vendors, cash and the lease, and every change they make
to the shop, goes through the tools defined here.

Putting the database behind a tool boundary is what makes the shop's rules
*structural* instead of merely instructions in a prompt:

- An agent **cannot** move money. `request_payment` and `request_purchase_order`
  only ever write a `pending` row to the `approvals` table. Cash is debited in
  `supervisor_resolve_approval`, which runs only after a human clicks approve in
  the dashboard, and which the backend blocks agents from calling.
- An agent **cannot** overdraw the account. The cash floor is re-checked both
  when a payment is requested and again when it is executed, so the balance can
  never go below zero.
- An agent **cannot** order from a vendor that is holding shipments.
  `request_purchase_order` refuses outright while that vendor has an unpaid
  invoice.
- An agent **cannot** contact a real person. `draft_message` writes to the
  `drafts` table and there is no send path anywhere in the codebase.

## Database

Connects to **`data/campus_customs_new.db`** — the working copy.

The pristine `data/campus_customs.db` extracted from `data.zip` is never opened
for writing; it exists purely as the reset source, so a full ticket-resolution
run can always start from the original state.

The server adds four tables to the working copy on startup (`approvals`,
`purchase_orders`, `drafts`, `activity_log`); these are documented in
[`../output/harness.md`](../output/harness.md).

## Framework note

Built with **FastMCP**, which was renamed to `MCPServer` in the Python MCP SDK
v2 (`from mcp.server.mcpserver import MCPServer`). This project uses `mcp 2.3.0`,
so the current class name appears in the code; it is the same framework the
assignment refers to.

## The three essential tools

These three were implemented first because each one unblocks exactly one of the
three tickets sitting open on the board.

### 1. `check_inventory(sku, size)` → **Ticket 101**

Reads the `inventory` table. Ticket 101 is a customer order for one
`CC-TEE-WHITE` in size **S**, and because `inventory` is keyed on `sku` *and*
`size`, this tool is what reveals that the S row holds **`qty = 0`** while other
sizes still have stock — the fact that turns the ticket from "pick it off the
shelf" into "this needs a restock".

### 2. `request_payment(kind, ref_id, amount, memo, requested_by, ticket_id)` → **Ticket 102**

Reads `leases` and `cash_accounts`, writes to `approvals`. Ticket 102 is the
landlord's rent notice for lease 1, and this tool is what lets the Accounting
agent act on it — it verifies the amount against the lease's `monthly_rent`
(**$2,400**), confirms the balance covers it, and then queues it for the human
instead of paying it, which is the only way a payment is permitted to happen.

### 3. `quote_discount(sku, qty, discount_pct)` → **Ticket 103**

Reads the `pricing` table. Ticket 103 is the Yale AI Club asking for a bulk
discount on 20 hoodies, and this tool answers the only question that actually
decides the ticket — it takes `CC-HOOD-NAVY`'s `unit_cost` of **$22.00** against
its `list_price` of **$58.00** and returns the resulting gross margin plus the
**36.78%** ceiling beyond which the discount would breach the 40% margin floor.

## The full tool list (29)

Added in Problem 5 to cover what the agents actually needed: `find_restock_options`,
`get_payment_plan`, `post_board_note` and `list_board_notes`.

**Orientation** — `get_policies` (shop rule constants), `get_shop_overview`
(`desk`, `cash_accounts`, `tickets`, `inventory`, `invoices`, `vendors`,
`leases`, `approvals`).

**Tickets** — `list_tickets`, `get_ticket`, `assign_ticket`, `update_ticket`
(all on `tickets`, with `get_ticket` joining in the linked invoice, lease,
stock and pricing).

**Inventory** — `check_inventory` (`inventory`), `low_stock_report`
(`inventory`, `pricing`), `reserve_stock` (`inventory`, refuses rather than
going negative), `find_restock_options` (`inventory`, `pricing`, `vendors`,
`invoices`, `cash_accounts`, `desk` — shortfall, cost, every vendor's lead time
and hold status, and affordability in one call).

**Pricing** — `get_pricing`, `quote_discount` (both `pricing`).

**Vendors and facilities** — `list_vendors` (`vendors`), `get_vendor_status`
(`vendors`, `invoices`, `desk`), `list_leases` (`leases`, `desk`).

**Money, read** — `get_cash` (`cash_accounts`, `approvals`), `get_payment_plan`
(`cash_accounts`, `invoices`, `leases`, `approvals`, `desk` — the whole
prioritisation picture at once), `list_invoices`, `list_payments`,
`list_purchase_orders`, `list_approvals`, `get_approval`.

**Money, request only** — `request_payment` and `request_purchase_order`. These
validate the amount against the source record, check the cash floor, and then
write a `pending` row to `approvals`. **They never move money.**

**Money, execution** — `supervisor_resolve_approval`. Writes `approvals`,
`payments`, `cash_accounts` and then `invoices` / `leases` / `purchase_orders`
by kind. No agent has this tool: it is absent from all five allowlists and
additionally hard-blocked in the backend's tool-call interceptor.

**Communications** — `draft_message` and `list_drafts` (`drafts`, always
`status='draft'`), `post_board_note` and `list_board_notes` (`activity_log`).

## Per-agent allowlists

The backend gives each agent only the tools its role needs, via PydanticAI's
`toolset.filtered(...)`: Boss 10, Inventory 12, Accounting 14, Facilities 8,
Customer Service 5. This bounds what any single agent can do wrong, and keeps
the tool schema small on every model call.

## Running it

```bash
.venv/Scripts/python.exe -m mcp_server.server --port 8787
```

Serves Streamable HTTP at `http://127.0.0.1:8787/mcp`. Pass
`--transport stdio` to run it over stdin/stdout instead, which is how
`.mcp.json` at the project root connects the vibe coder to it.

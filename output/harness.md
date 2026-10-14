# Campus Customs Harness

Living design document for the Campus Customs multi-agent operation. Expanded as
each problem is tackled.

---

## 1. The database

| File | Role |
| --- | --- |
| `data/campus_customs.db` | The pristine database extracted from `data.zip`. **Never written to.** It is the reset source. |
| `data/campus_customs_new.db` | The working copy. The MCP server and the FastAPI backend both point here, and every tool mutation lands here. A reset simply re-copies the pristine file over it. |

The shop runs on its own clock: **`desk.date_today` = `2026-08-31`**. Every
"overdue", "due in N days" and delivery-ETA calculation in this project is done
against that date, never against the real-world date.

Opening cash: **$3,400.00** in the `checking` account. Revenue is not modeled, so
cash only ever goes *down*.

---

## 2. Tables shipped with the database

### `desk` — the shop's clock
**Fields:** `date_today`, `notes`

The single source of truth for what "today" means, so every agent computes
overdue invoices and delivery dates from the same date instead of the wall clock.

### `tickets` — the board
**Fields:** `id`, `type`, `requester`, `subject`, `sku`, `size`, `qty`,
`lease_id`, `invoice_id`, `status`, `notes`, `created_at`

This is the agents' inbox and the unit of work: the Boss reads it, assigns each
ticket to a specialist, and the run is finished when every ticket has a status
and a resolution.

### `inventory` — stock on hand
**Fields:** `sku`, `name`, `size`, `qty`, `location` *(primary key: `sku` + `size`)*

Tells the Inventory agent whether an order can actually be filled off the shelf,
and the per-size granularity is what exposes the shortages that drive restocking.

### `pricing` — cost and list price per SKU
**Fields:** `sku`, `unit_cost`, `list_price`

Lets the Accounting agent verify that a requested discount still clears the
margin floor, and prices out what a restock will cost in cash.

### `vendors` — who we buy from
**Fields:** `id`, `name`, `specialty`, `lead_days`

The Inventory agent matches a shortage to the right supplier by `specialty`, and
`lead_days` is what turns an approved purchase order into a promised arrival date.

### `leases` — the physical shop space
**Fields:** `id`, `space_name`, `landlord`, `monthly_rent`, `next_due`, `notes`

The Facilities agent's domain: it holds the rent amount and the next due date
that decide whether a rent notice is urgent and how much cash must be set aside.

### `cash_accounts` — the money available
**Fields:** `name`, `balance`, `date`

The hard constraint on everything: every payment is checked against this balance,
and the balance may never be driven below zero.

### `invoices` — what we owe vendors
**Fields:** `id`, `vendor_id`, `amount`, `due_date`, `status`, `description`

Drives two separate decisions at once — what Accounting must pay, and which
vendors are refusing to ship because they have not been paid.

### `payments` — the money that actually left
**Fields:** `id`, `kind`, `ref_id`, `amount`, `account`, `paid_at`, `approved_by`

The audit trail proving a human authorized every outflow; `approved_by` is the
record that the human-approval rule was honored.

---

## 3. Tables added to the working copy

These four live only in `campus_customs_new.db`, created by
`shop_db/db.py` on startup. A reset wipes them along with everything else.

### `approvals` — the human-in-the-loop queue
**Fields:** `id`, `kind`, `ref_id`, `ticket_id`, `amount`, `account`, `memo`,
`payload`, `status`, `requested_by`, `requested_at`, `decided_by`, `decided_at`,
`decision_note`, `result`

The gate that makes the approval rule structural rather than a promise in a
prompt: agent tools can only ever write a `pending` row here, and money moves
only when a human flips it to `approved`.

### `purchase_orders` — restocks placed with vendors
**Fields:** `id`, `vendor_id`, `sku`, `size`, `qty`, `unit_cost`, `total`,
`status`, `expected_date`, `invoice_id`, `ticket_id`, `approval_id`, `created_at`

Records what was ordered and — via `expected_date`, derived from the vendor's
lead time — the arrival date the Customer Service agent can honestly quote.

### `drafts` — the outbox that never sends
**Fields:** `id`, `ticket_id`, `channel`, `recipient`, `subject`, `body`,
`author`, `status`, `created_at`

Where every customer and vendor message lands. `status` is always `draft`;
there is no send path in the codebase, which is how "no real emails, no real
vendor calls" is enforced.

### `activity_log` — what the agents did
**Fields:** `id`, `run_id`, `ts`, `kind`, `agent`, `ticket_id`, `summary`, `detail`

Persists the agent conversation, handoffs and tool calls so the React dashboard
can replay a run instead of only showing the final state.

---

## 4. How the tables connect

```
                         desk.date_today  ──(drives every date calculation)
                                  │
   tickets ──sku/size──▶ inventory ──sku──▶ pricing
      │                      │
      │                      └──shortage──▶ vendors ──lead_days──▶ expected arrival
      │                                        │
      ├──invoice_id──▶ invoices ──vendor_id────┘   (unpaid ⇒ vendor will not ship)
      │                   │
      └──lease_id──▶ leases                     
                          │
          invoices + leases ──▶ approvals ──human click──▶ payments ──▶ cash_accounts
```

The single most important edge is `invoices.vendor_id`: an unpaid invoice does
not merely cost money, it **blocks that vendor from shipping anything**, which is
what chains an accounting problem onto an inventory problem.

---

## 5. The three open tickets

### Ticket 101 — customer order (Tauhid Zaman, `customer_order`)
Wants **1 × `CC-TEE-WHITE` size S**.

- `inventory` says **0 on hand** — it cannot be filled off the shelf.
- The ticket links to `invoice_id = 501`: **$840, status `open`, due 2026-08-28 —
  3 days overdue**, owed to vendor 1, **Bulldog Print Co**, for a rush reprint of
  this exact SKU.
- Bulldog Print Co is the `apparel reprint` vendor with a **5-day lead time**, but
  it is **on hold** until invoice 501 is settled.
- So the chain is: pay invoice 501 → vendor unblocks → restock PO → **ETA 2026-09-05**.
  A restock of 1 tee costs only $8 at `unit_cost`.

**This ticket cannot be resolved by the Customer Service agent alone** — it needs
Accounting to clear the invoice and Inventory to place the order.

### Ticket 102 — rent notice (Elm City Properties, `rent_notice`)
Links to `lease_id = 1`: **Chapel Street shop, $2,400/month, next due 2026-09-02
— 2 days away.** Facilities owns it, Accounting has to fund it, and it needs a
human approval click like any other payment.

### Ticket 103 — bulk discount request (Yale AI Club, `price_override`)
Wants **20 × `CC-HOOD-NAVY` size M** at a bulk discount.

- `inventory` shows **8 on hand** → a **shortfall of 12**.
- `pricing` is `unit_cost 22.00` / `list_price 58.00`. At the 40% gross-margin
  floor the discounted price cannot fall below **$36.67**, which caps the
  discount at **36.8%**.
- Restocking the missing 12 hoodies would cost **12 × $22 = $264**.

### The cash squeeze that ties all three together

| Outflow | Amount |
| --- | ---: |
| Opening cash | **$3,400.00** |
| Invoice 501 (unblocks the tee vendor) | −$840.00 |
| September rent | −$2,400.00 |
| **Remaining** | **$160.00** |

$160 covers the $8 tee reprint comfortably but **cannot cover the $264 hoodie
restock**. The board is therefore not three independent tickets — it is a single
prioritization problem, and the agents have to decide what the shop can afford
rather than approving everything in sight.

---

## 6. The MCP server

`mcp_server/server.py`, built on FastMCP (`MCPServer` in Python MCP SDK v2),
connected to **`data/campus_customs_new.db`**. It is the only component with
write access to the shop, so every rule below is enforced in code rather than
trusted to a prompt.

### The three essential tools

| Tool | Table(s) it accesses | Ticket it resolves |
| --- | --- | --- |
| `check_inventory(sku, size)` | `inventory` | **Ticket 101** |
| `request_payment(kind, ref_id, amount, memo, requested_by, ticket_id)` | `leases`, `cash_accounts` → writes `approvals` | **Ticket 102** |
| `quote_discount(sku, qty, discount_pct)` | `pricing` | **Ticket 103** |

**`check_inventory` → Ticket 101.** Because `inventory` is keyed on `sku` *and*
`size`, this tool is what exposes that the `CC-TEE-WHITE` / `S` row holds
`qty = 0` while M, L and XL still have stock, which is the fact that converts
Tauhid Zaman's order from a shelf pick into a restock problem.

**`request_payment` → Ticket 102.** Elm City Properties' rent notice points at
lease 1, and this tool is what lets Accounting act on it — it checks the
requested amount against that lease's `monthly_rent` of $2,400, confirms
`cash_accounts.balance` covers it, and then files it in `approvals` for the human
rather than paying it, which is the only route by which rent is allowed to be paid.

**`quote_discount` → Ticket 103.** The Yale AI Club's bulk request turns entirely
on whether the discount still earns the shop money, and this tool answers exactly
that by pulling `CC-HOOD-NAVY`'s `unit_cost` of $22.00 against its `list_price`
of $58.00 and returning both the resulting gross margin and the 36.78% discount
ceiling that the 40% margin floor implies.

### Safety properties enforced by the tools

| Rule | Where it lives |
| --- | --- |
| No payment without a human | `request_payment` / `request_purchase_order` only write a `pending` approval; cash moves solely in `supervisor_resolve_approval`, which agents are blocked from calling |
| Balance never below zero | Cash floor checked at request time *and* re-checked at execution time |
| Vendors on hold do not ship | `request_purchase_order` refuses while that vendor has an unpaid invoice |
| No real emails or vendor calls | `draft_message` writes to `drafts` with `status = 'draft'`; no send path exists |
| Shop clock, not wall clock | Every date calculation reads `desk.date_today` |
| Stock never goes negative | `reserve_stock` returns the exact shortfall instead of decrementing past zero |

### Supporting tools

`get_policies`, `get_shop_overview`, `list_tickets`, `get_ticket`,
`assign_ticket`, `update_ticket`, `low_stock_report`, `reserve_stock`,
`get_pricing`, `list_vendors`, `get_vendor_status`, `list_leases`, `get_cash`,
`list_invoices`, `list_payments`, `list_purchase_orders`, `list_approvals`,
`get_approval`, `request_purchase_order`, `supervisor_resolve_approval`,
`draft_message`, `list_drafts`.

---

## 7. Connecting the vibe coder

`.mcp.json` at the project root registers the server with Claude Code:

```json
{
  "mcpServers": {
    "campus-customs": {
      "command": ".venv/Scripts/python.exe",
      "args": ["-m", "mcp_server.server", "--transport", "stdio"],
      "env": {}
    }
  }
}
```

The same `mcp_server/server.py` serves both transports: **stdio** for the vibe
coder via the config above, and **Streamable HTTP** on `127.0.0.1:8787/mcp` for
the FastAPI backend.

### Tool smoke evidence

`scripts/mcp_smoke.py` launches the server *from* `.mcp.json` and exercises all
three essential tools over the MCP protocol, writing `output/mcp_smoke.json`.
Each entry carries the prompt, the tool, the arguments, the raw output, and an
independent SQL query proving the output matches the working database.

| Ticket | Tool | Result | Verified against |
| --- | --- | --- | --- |
| 101 | `check_inventory` | `CC-TEE-WHITE` / `S` → `qty 0`, Aisle B | `inventory` row |
| 102 | `request_payment` | `pending_human_approval`, approval 1, $2,400 | `leases.monthly_rent`, plus cash unchanged at $3,400 and 0 `payments` rows |
| 103 | `quote_discount` | unit $43.50, margin 49.43%, passes, ceiling 36.78% | `pricing` row, figures recomputed from `unit_cost` $22.00 / `list_price` $58.00 |

All three reported `matches_database: true`.

---

## 8. The agent team

Built with **PydanticAI**. All five agents run on **`gpt-6-luna` only**, routed
through Portkey with `PORTKEY_API_KEY`. The model id lives in exactly one
constant, `backend/config.py:MODEL_ID`, so there is a single place to audit it.
`gpt-6-luna` rejects function tools on `/v1/chat/completions`, so the team runs
on the Responses API via `OpenAIResponsesModel`.

Every agent reaches the shop **only** through the MCP server. There is no second
data path: `backend/shop.py`, which feeds the dashboard, is itself an MCP client
and opens no database connection of its own.

| Agent | Prompt | Owns | Typically delegates to |
| --- | --- | --- | --- |
| **Boss** | `backend/prompts/boss.md` | Reads every ticket, assigns it, makes the final call, closes it | The one specialist whose job the ticket is |
| **Inventory** | `backend/prompts/inventory.md` | Stock by SKU *and* size, shortfalls, vendor choice, delivery dates | Accounting (blocked vendor, affordability), Customer Service (arrival date) |
| **Accounting** | `backend/prompts/accounting.md` | Cash, invoices, margins, queuing payments and POs | Facilities (lease facts), Boss (when cash cannot cover everything) |
| **Facilities** | `backend/prompts/facilities.md` | The shop space, the lease, the landlord, rent | Accounting (to file the rent payment) |
| **Customer Service** | `backend/prompts/customer_service.md` | Drafting replies to customers — drafts only | Whichever specialist owns a fact it is missing |

### Full connectivity

The team is a complete mesh. Every agent carries an `ask_<agent>` tool for every
other agent — 20 delegation tools across the five — so any agent can pull in any
teammate. Runaway loops are stopped structurally rather than by asking nicely:

- **Depth cap.** `MAX_DELEGATION_DEPTH = 3`. Past it, the delegation tool returns
  a refusal telling the agent to answer with what it already has.
- **Cycle guard.** `ShopDeps.call_stack` tracks who is currently waiting further
  up the chain. Delegating back into an agent already on the stack is refused,
  so A → B → A cannot happen.
- **Shared usage.** A nested run is passed the parent's usage object, so a whole
  delegation tree counts against one ticket's budget.

Each refusal is written to the audit trail as `delegation_refused`, so a run that
hits a limit is visible rather than silent.

### Observed routing

A real run of ticket 102 produced exactly the intended shape — two specialists,
not five:

```
boss          get_ticket, assign_ticket
  └─ facilities    list_leases, get_shop_overview, get_ticket
       └─ accounting   get_payment_plan, request_payment  →  approval #1 queued
boss          update_ticket  →  resolved, awaiting approval 1
```

Cash stayed at $3,400.00 and the `payments` table stayed empty: the agents
queued the rent, they did not pay it.

### Audit trail

`backend/audit.py` appends every step to **`output/audit_trail.json`** as a
growing JSON array. The file is loaded on startup and **appended to, never
truncated**, so it spans every run in the project's history. Writes are atomic
(temp file plus `os.replace`), and an unreadable trail is moved aside rather than
destroyed.

Recorded event kinds: `run_started`, `ticket_started`, `agent_started`,
`delegation`, `delegation_refused`, `tool_call`, `tool_result`,
`approval_requested`, `approval_resolved`, `agent_finished`, `ticket_finished`,
`limit_reached`, `error`, `run_finished`. Each carries the run id, a sequence
number, a UTC timestamp, the agent, the ticket, the delegation depth, the tool
name with its arguments and result, and token counts.

---

## 9. Every MCP tool and the table it touches

29 tools. Writes are marked; everything else is read-only.

### Orientation
| Tool | Tables |
| --- | --- |
| `get_policies` | none — returns the shop's rule constants |
| `get_shop_overview` | `desk`, `cash_accounts`, `tickets`, `inventory`, `invoices`, `vendors`, `leases`, `approvals` |

### Tickets
| Tool | Tables |
| --- | --- |
| `list_tickets` | `tickets` |
| `get_ticket` | `tickets`, joined to `invoices`, `leases`, `inventory`, `pricing` |
| `assign_ticket` ✏️ | `tickets` |
| `update_ticket` ✏️ | `tickets` |

### Inventory
| Tool | Tables |
| --- | --- |
| `check_inventory` | `inventory` |
| `low_stock_report` | `inventory`, `pricing` |
| `reserve_stock` ✏️ | `inventory` |
| `find_restock_options` | `inventory`, `pricing`, `vendors`, `invoices`, `cash_accounts`, `desk` |

### Pricing
| Tool | Tables |
| --- | --- |
| `get_pricing` | `pricing` |
| `quote_discount` | `pricing` |

### Vendors and facilities
| Tool | Tables |
| --- | --- |
| `list_vendors` | `vendors` |
| `get_vendor_status` | `vendors`, `invoices`, `desk` |
| `list_leases` | `leases`, `desk` |

### Money — read
| Tool | Tables |
| --- | --- |
| `get_cash` | `cash_accounts`, `approvals` |
| `get_payment_plan` | `cash_accounts`, `invoices`, `leases`, `approvals`, `desk` |
| `list_invoices` | `invoices`, `vendors`, `desk` |
| `list_payments` | `payments` |
| `list_purchase_orders` | `purchase_orders`, `vendors` |
| `list_approvals` | `approvals` |
| `get_approval` | `approvals` |

### Money — request only, never executes
| Tool | Tables |
| --- | --- |
| `request_payment` ✏️ | reads `invoices`, `leases`, `cash_accounts` → writes `approvals` |
| `request_purchase_order` ✏️ | reads `vendors`, `invoices`, `pricing`, `inventory`, `cash_accounts`, `desk` → writes `approvals` |

### Money — execution, human only
| Tool | Tables |
| --- | --- |
| `supervisor_resolve_approval` ✏️ | writes `approvals`, `payments`, `cash_accounts`, and then `invoices` / `leases` / `purchase_orders` depending on the kind |

**No agent has this tool.** It is excluded from all five allowlists and
additionally hard-blocked in `backend/agents.py:_audit_tool_calls`, which raises
`PermissionError` if a model ever names it. Only `backend/shop.py` calls it, and
only when a human clicks approve or deny.

### Communications — drafts only
| Tool | Tables |
| --- | --- |
| `draft_message` ✏️ | `drafts` (always `status='draft'`) |
| `list_drafts` | `drafts` |
| `post_board_note` ✏️ | `activity_log` |
| `list_board_notes` | `activity_log` |

### Who gets what

Each agent is given a narrow allowlist via PydanticAI's `toolset.filtered(...)`,
defined in `backend/agents.py:AGENT_TOOLS`: Boss 10 tools, Inventory 12,
Accounting 14, Facilities 8, Customer Service 5 — plus four delegation tools
each. Narrow allowlists are a cost control as much as a safety one, since the
tool schema is re-sent on every model call.

---

## 10. Safety

### Guardrails a real shop would need before letting agents touch money

1. **A human on every outflow, enforced by the architecture.** It is not enough
   to tell a model not to spend money. Here the tools an agent can reach are
   physically incapable of moving cash — they write a `pending` row and return.
   Execution lives behind a separate tool that is filtered out of every agent's
   toolset *and* blocked at the call interceptor. A prompt injection in a
   customer's message cannot talk its way past a tool that is not there.
2. **Amounts validated against the source record.** A payment must match the
   invoice's amount or the lease's rent exactly. An agent cannot pay $8,400 on an
   $840 invoice by fumbling a digit.
3. **A hard floor on the balance, checked twice.** Once when queued and again at
   execution, because the balance can move in between. The shop cannot be
   overdrawn even by an approved payment.
4. **Idempotent requests.** An identical pending request is returned rather than
   duplicated, so a retrying agent cannot queue the same rent four times.
5. **No outbound channel at all.** The safest way to guarantee nothing is sent to
   a real customer is for no send path to exist in the codebase. Drafts go to a
   table a human reads.
6. **Least privilege per role.** Customer Service cannot request a payment.
   Facilities cannot reserve stock. The blast radius of any one agent going wrong
   is bounded by its allowlist.
7. **A complete, append-only audit trail.** Every tool call, argument, result,
   delegation and refusal is recorded with who did it and when. A business needs
   to be able to answer "why did we pay this?" months later.
8. **Named human accountability.** `payments.approved_by` records the person, not
   "the system". Approval is attached to someone who can be asked about it.
9. **Honest reporting of pending state.** Every prompt stresses that queued is
   not paid. An agent that tells a customer "your order is on its way" when the
   PO is unapproved is a business problem, not just a wording problem.
10. **A reset path.** The pristine database is never written to, so any run can
    be replayed from a known state — essential for testing agents that touch
    money.

### What is deliberately *not* guarded, and would need to be in production

Authentication on the MCP server (it binds to localhost and trusts its caller),
rate limiting, encryption of the database at rest, and segregation of duties
between the person who requests a payment and the person who approves it.

### Token controls

Multi-agent loops are where budgets disappear, so every limit is explicit in
`backend/config.py`:

| Control | Value | Why |
| --- | --- | --- |
| `MAX_DELEGATION_DEPTH` | 3 | Boss → specialist → specialist, then stop |
| `MAX_REQUESTS_PER_TICKET` | 40 | ceiling on model calls across a ticket's whole tree |
| `MAX_TOOL_CALLS_PER_TICKET` | 60 | catches a tool-call loop early |
| `MAX_TOTAL_TOKENS_PER_TICKET` | 180,000 | a runaway ticket is capped, not the whole run |
| `MAX_OUTPUT_TOKENS` | 1,400 | per response; the agents report, they do not write essays |
| `AGENT_RETRIES` | 2 | bounded retries on validation failure |

Enforced by PydanticAI's `UsageLimits`, with usage shared down the delegation
tree so nested runs count against the same ticket budget. Beyond the hard caps:

- **Narrow per-agent toolsets** keep the tool schema small on every call.
- **Composite tools** — `get_shop_overview`, `find_restock_options` and
  `get_payment_plan` each replace four to six separate round trips.
- **`cache_tools=True`** on the MCP toolset avoids re-listing tool schemas.
- **Cycle refusal** stops two agents consulting each other indefinitely.
- **Prompts instruct brevity** and tell agents to pass context down when
  delegating so the callee does not re-fetch what the caller already has.
- **One ticket at a time**, so a failure costs one ticket's budget, not the run's.

Measured: ticket 102 end to end cost **11 requests, 10 tool calls, 27,903
tokens**.

---

## 11. Backend routes

FastAPI in `backend/main.py`. Started from inside `backend/` with
`uvicorn main:app --reload --port 8000`. CORS allows the Vite origin
`http://localhost:5173`. Every shop fact served here is fetched through the MCP
server — the backend opens no database connection of its own, with the single
exception of `/api/reset`, which is a file-level restore of the database
artifact rather than a shop-data path.

| Route | What it does |
| --- | --- |
| `GET /api/health` | Service health, the model in use, and whether the MCP server is reachable |
| `GET /api/tickets` | All three tickets with an `is_open` flag plus open/resolved counts |
| `GET /api/tickets/{id}` | One ticket with its linked invoice, lease, stock and pricing |
| `POST /api/tickets/{id}/run` | Hands that ticket to the agent team; returns a `run_id` immediately, or blocks when `wait: true` |
| `GET /api/runs/{run_id}` | Status and final result of one agent run |
| `GET /api/runs` | Every run this process has started, and which is active |
| `GET /api/activity` | Latest agent activity — what each agent said and which tools it called — paged by `after` cursor for live refresh |
| `GET /api/cash` | Current checking balance from the `cash_accounts` table, plus what is committed to pending approvals |
| `GET /api/approvals` | Payment and purchase-order requests, filterable by status |
| `POST /api/approvals/{id}/decision` | Records the supervisor's approve/deny — **the only route that moves cash** |
| `GET /api/payment-plan` | Cash against every obligation, for prioritising |
| `GET /api/board` | Full shop snapshot in one call: tickets, inventory, invoices, leases, payments, POs, drafts, notes, approvals |
| `GET /api/drafts` | Customer message drafts on the board — never sent |
| `POST /api/reset` | Restores the working database from the pristine copy for a fresh run |

Only one run is permitted at a time; a second `POST .../run` returns `409` while
one is active, which keeps concurrent agents from racing on the same cash.

---

## 12. The dashboard

`frontend/`, built with React, Vite and TypeScript. Calls the backend at
`http://localhost:8000`; the backend allows CORS from the Vite origin
`http://localhost:5173`. Start it with `npm run dev`.

A three-column operator desk, ordered the way the work flows:

| Column | Contents |
| --- | --- |
| **The board** | All three tickets with status badges, the assigned agent, and the Boss's resolution text. Selecting one reveals the "Hand to the agent team" button. |
| **Agent floor** | The live feed — every agent message, every MCP tool call with its arguments, every delegation, and every approval request, in order. |
| **Your desk** | The checking balance, the approval queue with Approve/Deny, and a per-agent recap of what each one did. |

Nothing requiring human action is ever rendered in the middle column, so the
right edge is the only place the operator has to watch.

**Distinguishing the agents.** Each agent owns a colour used on its avatar, its
name in the feed, its roster chip and its recap card — Boss pink, Inventory
amber, Accounting mint, Facilities violet, Customer Service cyan, the human
white. Speech is rendered as prose, tool calls as monospace pills on black, and
delegations as pink chips naming the target in that agent's own colour. Tool
*results* are recorded in the audit trail but not drawn, since the raw JSON
would bury the conversation.

**Cash.** The balance is the largest element on screen. When it changes it turns
pink for two seconds and shows a delta (`-$840.00 just now`), so money leaving
the shop registers as an event. Cash committed to pending approvals is shown
separately from cash that is genuinely free.

**Live updates** use polling against `GET /api/activity?after=<cursor>` — 1.2s
while a run is active, 4s when idle — appending only new events. On load the
feed shows just the most recent run, since the audit trail deliberately spans
every run in the project's history.

Full rationale is in [`design.md`](design.md).

---

## 13. Running the whole stack

Three processes, in this order:

```bash
# 1. the MCP server -- the only writer to the shop database
.venv/Scripts/python.exe -m mcp_server.server --port 8787

# 2. the agent backend
cd backend && uvicorn main:app --reload --port 8000

# 3. the dashboard
npm run dev --prefix frontend
```

Then open `http://localhost:5173`, press **Reset shop**, pick a ticket and hand
it to the team.

To drive a complete three-ticket run from the command line instead:

```bash
.venv/Scripts/python.exe -m scripts.full_run
```

---

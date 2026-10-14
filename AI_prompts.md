# AI Prompts Log — HW 5: Campus Customs Multi-Agent Operations

A complete, running log of every prompt given to the vibe coder on this project.

- **Vibe coder:** Claude Opus 5 (Claude Code, desktop app)
- **Author:** Yunsik Jung
- **Started:** 2026-10-11
- **Convention:** one section per assignment problem, in the order the problems were
  tackled. Each section records the initial prompt in my own words, plus any
  follow-up prompts with a one-line note on what the first prompt failed to achieve.

> Note on the agents' model: the five shop agents run exclusively on `gpt-6-luna`
> via Portkey, as the assignment requires. "Opus 5" above refers only to the
> coding assistant used to *write* this project, not to anything the agents call.

---

## Problem 0 — Project setup and scenario briefing

*(Not a graded problem; recorded because it is the prompt the whole project started from.)*

### Initial prompt

> 자 오늘은 HW 5 할 차례야. 우선 시나리오부터 줄게.
>
> **Scenario: Campus Customs Multi-Agent Operations**
>
> Campus Customs Multi-Agent Operations serves as the AI team managing the store.
> Various open tickets—such as customer orders, rent payments, outstanding bills,
> and discount inquiries—arrive on a central board. We need to develop three
> interconnected components: an MCP server, a FastAPI backend hosting the
> multi-agent team, and a React dashboard that allows a human supervisor to
> monitor agent activities and authorize requests.
>
> Our agents will operate with full connectivity, meaning any agent can assign
> tasks to another for assistance. We will be creating the following specific
> agents: **Boss** (reviews every ticket, assigns it, makes final decisions),
> **Inventory** (stock by SKU and size, shortages, correct vendor for restocking),
> **Accounting** (cash flow and invoices, profit margins, drafts payments or
> purchase orders requiring human sign-off), **Facilities** (physical shop space,
> leases and rent), **Customer Service** (drafts responses to customers).
>
> **Data setup:** download and extract `data.zip` to get `data/campus_customs.db`
> with tables for `desk`, `tickets`, `inventory`, `pricing`, `vendors`, `leases`,
> `cash_accounts`, `payments`, `invoices`. Make a duplicate named
> `data/campus_customs_new.db` and point the MCP server and backend at the copy,
> so the original stays pristine for resets.
>
> **Rules of this shop:** `desk.date_today` is the store's current date and drives
> every overdue calculation; vendor lead times come from the `vendors` table;
> vendors withhold shipping while they have unpaid invoices; every payment
> strictly requires human approval (failing to implement this is a penalty) and
> the matching table must be updated whenever a payment executes; the payment
> tool must reject transactions when cash is insufficient so balances never drop
> below zero; cash is strictly outgoing because revenue is not modeled; the
> database must be reset to its initial state before a full ticket-resolution run;
> we only draft messages on the board and must absolutely not send real emails to
> customers or call actual vendors.
>
> **AI and workflow constraints:** use `PORTKEY_API_KEY` for all AI requests;
> use exclusively the `gpt-6-luna` model via Portkey across all agents, since any
> other model costs points. Tackle each problem sequentially with the vibe coder,
> explaining tasks in our own words rather than pasting the assignment URL or
> screenshots. The submission is a public GitHub repository.

### Follow-up prompt 1 — architecture decisions

The initial prompt described *what* to build but left three implementation
choices open, so the vibe coder asked and I picked:

> - MCP transport: **Streamable HTTP service** (the MCP server runs as its own
>   process on a port, so it is visibly a third component and any MCP client can
>   connect to it).
> - Approval flow: **"Just execute everything without approval except something
>   related with security."**
> - Agent runtime: **Custom orchestrator loop** on the Responses API rather than
>   the OpenAI Agents SDK, for full control over event streaming and approval
>   blocking.

The vibe coder pushed back on the middle answer, because the assignment states
every payment strictly requires human approval or points are deducted. We settled
on the reading that satisfies both: **money-moving, sensitive actions (payments
and purchase orders) gate on a human click; everything else — inventory lookups,
ticket assignment, stock reservation, drafting replies — runs with no prompts.**

### Follow-up prompt 2 — model clarification

> And I'll use opus 5 rather than gpt

*What the first prompt left ambiguous:* it was unclear whether "Opus 5" meant the
model the five shop agents run on or just the coding assistant building the
project. Swapping the agents off `gpt-6-luna` would be an explicit point
deduction, so the vibe coder asked; the answer was **the vibe coder only** —
the agents stay on `gpt-6-luna`.

---

## Problem 1 — Vibe coder prompts (5 points)

### Initial prompt

> 자 문제 1번이야.
> 앞으로 각 지시사항이 있을 때마다 수행하고 난 뒤에
> 1) 어떤 지시사항이 있었는지 (한글로, 요약 + 쉽게 설명)
> 2) 지시사항을 어떤 방식으로 이행했는지
> 3) 결과물은 어떤 상태이며, 향후 어떻게 펼쳐질것인지
> 한글로 꼭 설명하고 다음 문제에 돌입하도록 해.
>
> **Problem 1: Vibe coder prompts (5 points)**
>
> *[Panel A]* We need to generate a file called `AI_prompts.md` at the very
> beginning of our project and continuously update it as we progress. This
> document will act as a complete log of every prompt we submit to our vibe coder.
>
> *[Panel B]* We must create a dedicated section for each individual problem.
> Within every section, we have to include: the problem's number and title; at
> least one initial prompt written primarily in our own words; a follow-up prompt
> if we needed one, including a brief one-sentence explanation of what the first
> prompt failed to achieve.

### How it was carried out

Created this file (`AI_prompts.md`) at the project root, backfilled the prompts
already given during setup as **Problem 0**, and adopted a standing convention:
every new instruction gets appended here as its own section before the work on
that problem is reported back. A standing requirement was also added — after each
instruction the vibe coder explains in Korean what was asked, how it was done,
and where the deliverable stands.

*No follow-up prompt was needed for this problem.*

---

## Problem 2 — Study the Campus Customs database (8 points)

### Initial prompt

> **Problem 2: Study the Campus Customs database (8 points)**
>
> *[Panel A]* We need to open `data/campus_customs.db` and carefully examine all
> the tables along with their respective fields. We must make a copy of this
> original database and name it `data/campus_customs_new.db`, as our subsequent
> tasks will modify this new working copy. Additionally, we should analyze the
> three currently open tickets to understand their relationships with the other
> tables.
>
> *[Panel B]* We should initiate a file named `output/harness.md`. Inside this
> file, we need to document each table by listing its fields and providing a
> brief, one-sentence explanation of why that specific table is important for our
> agents. We will continue to expand this harness document as we tackle the
> upcoming problems.

### How it was carried out

Extracted `data.zip`, dumped the full schema and every row of all nine shipped
tables, and copied the pristine file to `data/campus_customs_new.db`. Ran a join
query across `tickets → inventory → pricing → vendors → invoices → leases` to
work out what each of the three open tickets actually depends on, computing the
numbers rather than eyeballing them: invoice 501 is 3 days overdue, the tee is
0-on-hand, the hoodie is 12 short, the 40% margin floor caps the hoodie discount
at 36.8%, and paying both the invoice and the rent leaves exactly $160.

Wrote `output/harness.md` with a section per table (fields plus a one-sentence
reason it matters to the agents), a relationship map, the three-ticket analysis,
and the cash-squeeze table that explains why the board is one prioritization
problem rather than three independent tickets. The four tables added to the
working copy for this project — `approvals`, `purchase_orders`, `drafts`,
`activity_log` — are documented in their own section.

*No follow-up prompt was needed for this problem.*

---

## Problem 3 — Build the MCP server (12 points)

### Initial prompt

> **Problem 3: Build the MCP server (12 points)**
>
> *[Panel A]* We need to develop an MCP server located within the `mcp_server/`
> directory, utilizing the FastMCP framework. This server will interact directly
> with our `data/campus_customs_new.db` file. Note that we don't have to actually
> connect or run the server during this specific problem step. Since all the
> agents in this assignment will rely on the tools provided by this MCP server, we
> must start by implementing three essential tools that we know are necessary to
> process the tickets currently in the database. We must give these tools clear,
> descriptive names, and strictly rely only on the data present in the
> database—never fabricating or inventing any information.
>
> *[Panel B]* In our `output/harness.md` file, we must document each of the three
> MCP tools we just created. For every tool, we need to specify: which database
> table it accesses; which specific ticket it helps resolve (Ticket 101, 102, or
> 103); exactly one sentence explaining why this tool is the correct solution for
> that particular ticket. We must avoid vague descriptions like "reads inventory"
> and ensure we explicitly connect the tool's function to the ticket. Finally, we
> need to create a brief `mcp_server/README.md` file explaining the purpose of the
> MCP server, the database file it connects to, and the three tools implemented.

### How it was carried out

Built `mcp_server/server.py` on FastMCP against the working copy of the database.
Three tools were nominated as the essential ones, each keyed to one ticket and a
different table: `check_inventory` (`inventory` → Ticket 101), `request_payment`
(`leases` + `cash_accounts` → `approvals` → Ticket 102) and `quote_discount`
(`pricing` → Ticket 103). Every value they return is read or computed from the
database; nothing is hard-coded. Supporting tools for the rest of the board were
implemented alongside them.

The shop rules were pushed down into the tools rather than left to prompts: the
payment tools can only queue a `pending` approval, execution lives in
`supervisor_resolve_approval`, the cash floor is checked twice, purchase orders
are refused while a vendor holds unpaid invoices, and `draft_message` has no send
path. Documented the three tools in `output/harness.md` section 6 with the
table, the ticket and the one-sentence justification each, and wrote
`mcp_server/README.md`.

### Follow-up prompt — none, but two issues were found and fixed while verifying

*What the first prompt's approach failed to achieve:* Panel A said the server did
not need to be run, but a quick in-process smoke test surfaced two real defects
that would have broken later problems — `with sqlite3.connect(...)` commits
without closing, so every tool call leaked a file handle, and the resulting WAL
lock made the database reset fail on Windows with `PermissionError`. Both were
fixed in `shop_db/db.py` (a closing context manager, plus a WAL checkpoint before
reset) and the reset now restores cash to $3,400.00 with zero approvals.

---

## Problem 4 — Add the MCP server to vibe coder and test each tool (8 points)

### Initial prompt

> **Problem 4: Add the MCP server to vibe coder and test each tool (8 points)**
>
> *[Panel A]* We need to integrate our MCP server into this project using our
> vibe coder (such as Claude Code) so that the coder can directly access and
> execute the tools. We should save the connection configuration as JSON text in
> a `.mcp.json` file located at the root of our project (or use whichever method
> our specific vibe coder employs to store local MCP server lists).
>
> *[Panel B]* Once our vibe coder is successfully connected, we must
> systematically test every single one of our three MCP tools. We need to record
> the evidence of these successful tests in `output/mcp_smoke.json`. For each tool
> we evaluate, our documentation must include: the exact prompt we submitted to
> the vibe coder; the name of the specific tool used; the resulting output from
> the tool, which must perfectly match the existing values found in
> `data/campus_customs_new.db`.

### How it was carried out

Wrote `.mcp.json` at the project root registering the `campus-customs` server as
a stdio subprocess (`.venv/Scripts/python.exe -m mcp_server.server --transport
stdio`), which is how Claude Code stores local MCP servers.

For the evidence, `scripts/mcp_smoke.py` reads that same `.mcp.json` and launches
the server from it, so the test exercises the exact configuration that is checked
into the repo, over the real MCP protocol rather than by importing the Python
functions. It calls all three tools and, for each, runs an **independent SQL
query against `data/campus_customs_new.db`** and compares it to the tool output,
recording a `matches_database` verdict. The database is reset to the pristine
state first so the evidence is reproducible.

All three tools returned `MATCH` against the database, across 25 exposed tools.
The `request_payment` check additionally records cash before and after plus the
payment row count, proving the approval was queued as `pending` while the balance
stayed at $3,400.00 with zero payments — the human-approval gate holding.

### Follow-up prompt — none

*Caveat recorded honestly:* `.mcp.json` is read by Claude Code at startup, so the
tools appear in the vibe coder's own tool list only after restarting it. The
evidence in `output/mcp_smoke.json` was produced by driving that same config
programmatically within the running session; the prompts recorded in the file are
the ones that exercise each tool once the server is loaded interactively.

---

## Problem 5 — Build the agent team and grow the MCP tools (15 points)

### Initial prompt

> **Problem 5: Build the agent team and grow the MCP tools (15 points)**
>
> *[Panel A]* We must construct the AI agent team for Campus Customs utilizing
> PydanticAI, specifically creating the Boss, Inventory, Accounting, Facilities,
> and Customer Service agents. We need to implement their prompts, assign their
> models, and set up their agent loops to ensure they have full connectivity to
> delegate tasks to one another. We should store the individual agent prompts
> inside `backend/prompts/`, making sure there is exactly one file per agent. All
> data types belong in `backend/models.py`, and the core agent scripts should be
> placed within the `backend/` directory. We must strictly use our
> `PORTKEY_API_KEY` and restrict every agent exclusively to the `gpt-6-luna`
> model. When drafting the prompts, we need to use our own phrasing and
> incorporate the specific shop rules relevant to each agent; comprehensive
> prompts will earn a higher score than brief, generic ones.
>
> *[Panel B]* Next, we need to expand our MCP server by adding any extra tools
> the agents require to resolve the open tickets. All factual information about
> the shop must be retrieved through the MCP server from
> `data/campus_customs_new.db` — we must absolutely not create an alternative
> layer for shop tools that circumvents the MCP architecture. We also need to
> configure the agents to continuously append their execution logs to
> `output/audit_trail.json`, recording sufficient detail for future auditing, and
> appending rather than wiping the file. Inside `output/harness.md` we must
> document every agent and every MCP tool (including the new ones), explicitly
> stating which database table each tool interacts with, plus a concise safety
> section on the guardrails a legitimate business would need when AI agents
> handle real currency and actual customers, along with constraints to control
> token consumption. Finally, update `mcp_server/README.md` to reflect the
> expanded tool list.

### How it was carried out

Switched the runtime to **PydanticAI**, which supersedes the custom-orchestrator
choice made during setup — that was a graded requirement not yet known at the
time.

Five agents in `backend/agents.py`, one prompt file each in `backend/prompts/`,
all types in `backend/models.py`, the append-only log in `backend/audit.py`, the
board runner in `backend/runner.py`, and all configuration in
`backend/config.py` with `MODEL_ID = "gpt-6-luna"` as the single auditable
constant.

**Full connectivity** is a complete mesh: each agent gets an `ask_<agent>` tool
for every teammate (20 delegation tools in total), with a depth cap of 3, a
cycle guard built on the call stack in `ShopDeps`, and usage shared down the
tree so a whole delegation chain counts against one ticket's budget.

**Panel B's "no alternative layer" rule drove a real design decision:** the
backend's own `backend/shop.py`, which feeds the dashboard, was written as an
MCP *client* rather than as direct SQL. Nothing outside the MCP server opens the
database. Four tools were added — `find_restock_options`, `get_payment_plan`,
`post_board_note`, `list_board_notes` — bringing the server to 29.

Documented all 29 tools with their tables in `output/harness.md` section 9, the
agents in section 8, and wrote section 10 covering ten business guardrails, what
is deliberately not guarded, and six token controls. Updated
`mcp_server/README.md`.

### Follow-up prompt — a 400 from the model forced a change of API

*What the first approach failed to achieve:* the team was built on
`OpenAIChatModel`, and the first live run died immediately with
`azure-openai error: Function tools with reasoning_effort are not supported for
gpt-6-luna-global in /v1/chat/completions. To use function tools, use
/v1/responses`. Since every agent in this design is tool-driven, the model was
switched to `OpenAIResponsesModel`, which also matches the Responses API pattern
used elsewhere in this course.

A verification run on ticket 102 then produced the intended shape — Boss →
Facilities → Accounting, two specialists rather than five — queuing approval #1
for $2,400 while cash stayed at $3,400.00 and the `payments` table stayed empty.
Cost: 11 requests, 10 tool calls, 27,903 tokens. The audit trail correctly
contains both the failed run and the successful one, proving it appends.

---

## Problem 6 — Plan the three tickets (8 points)

### Initial prompt

> **Problem 6: Plan the three tickets (8 points)**
>
> *[Panel A]* Prior to connecting the backend, we need to document our
> expectations for how the AI team will handle each open ticket. We must create
> an `output/desk_tickets.html` file — a simple page we can open by
> double-clicking — that features a separate tab for each ticket (101, 102, and
> 103). We should also include blank tabs for "Cash" and "Reflection" to prepare
> for upcoming problems. Within each ticket's tab, we need to complete only the
> "Expected" section, leaving space for an "Actual" section to fill in once the
> agents have been executed.
>
> *[Panel B]* Inside the Expected section for every ticket, we must describe in
> our own words: which agent the Boss needs to contact initially and the
> reasoning behind it; every specific agent delegation we anticipate (avoiding
> lazy plans like "the Boss just calls everyone"); and the exact MCP tools we
> predict will be utilized during that run. Strategies that unnecessarily involve
> every specialist for every ticket will receive a poor grade.

### How it was carried out

Wrote `output/desk_tickets.html` as a single self-contained file — no build step,
no external assets, opens by double-clicking — with five tabs: 101, 102, 103,
plus placeholder Cash and Reflection tabs. Styled black-and-pink per the house
convention.

Each ticket tab names one first-contact agent with the reasoning for it
(Inventory for 101 because stock gates everything downstream; Facilities for 102
because the landlord's claim has to be checked against the lease record;
Accounting for 103 because a discount is a margin question first), then lists the
specific delegation chain, an ASCII flow diagram, and the predicted tool calls.
Each tab also explicitly names **who should not be involved and why**, which is
the direct counter to the "Boss just calls everyone" pattern the rubric warns
against.

The predictions were made falsifiable rather than vague, so the Actual sections
can genuinely contradict them:

- **101** — the purchase order will be *refused* during this run, because the
  vendor is on hold until a human approves the $840 invoice; the ticket should
  end awaiting approval, not fulfilled.
- **102** — the amount must be exactly $2,400.00, and reporting it as paid rather
  than pending is a failure.
- **103** — the discount ceiling is 36.78%; a deeper discount breaks policy, and
  a round number like "20% off" means the agent guessed instead of calling
  `quote_discount`. The honest outcome is a discount on the 8 hoodies in stock
  with the other 12 deferred, since $160 remains after the invoice and rent and
  the restock costs $264.

*No follow-up prompt was needed for this problem.*

---

## Problem 7 — Backend routes (7 points)

### Initial prompt

> **Problem 7: Backend routes (7 points)**
>
> *[Panel A]* Our React frontend dashboard requires a functioning backend to
> interact with. We need to utilize FastAPI within `backend/main.py` to construct
> routes that: retrieve the three tickets and display whether each is open or
> resolved; accept a ticket ID and trigger our agent team to process it; fetch
> the latest agent activities — what each agent communicated and the tools they
> used — so the dashboard can dynamically refresh; process the final approval of
> a payment or purchase once a human supervisor clicks 'approve' (since the
> agents only prepare the payment, this route is the one that actually modifies
> the cash balance); return the current checking balance from the `cash_accounts`
> table; and restore the database to its initial defaults for a fresh run.
>
> *[Panel B]* We start the server from inside `backend/` with
> `uvicorn main:app --reload --port 8000`, serving at `http://localhost:8000`.
> Lastly, document these endpoints in `output/harness.md`, listing each route on
> a single line with its URL and function.

### How it was carried out

Wrote `backend/main.py` with all six required routes plus eight supporting ones.
Panel B's launch command runs uvicorn **from inside `backend/`**, which means the
module is imported as top-level `main`, not `backend.main` — so `main.py` puts
the repository root on `sys.path` before importing anything, and works either
way. Verified by importing it with the working directory set to `backend/`.

Runs are started as background tasks returning a `run_id` immediately, since an
agent run takes minutes and a dashboard needs to show progress rather than hang
on a request; `GET /api/activity` pages through the audit trail with an `after`
cursor so the board refreshes incrementally. A `wait: true` flag is available for
synchronous use. Only one run is allowed at a time — a second returns `409`, so
two runs cannot race on the same cash balance.

Verified live against the running stack: `/api/health` reports the MCP server
reachable and the model as `gpt-6-luna`, `/api/tickets` returns all three with
`is_open`, `/api/reset` restores cash to $3,400.00, and the approval route was
tested end to end — a queued $840 invoice payment approved through
`POST /api/approvals/1/decision` moved cash **$3,400.00 → $2,560.00**, marked
invoice 501 paid and wrote the `payments` row. Documented all 14 routes in
`output/harness.md` section 11.

*No follow-up prompt was needed for this problem.*

---

## Problem 8 — Agent dashboard (12 points)

### Initial prompt

> **Problem 8: Agent dashboard (12 points)**
>
> *[Panel A]* We need to develop the frontend dashboard within the `frontend/`
> directory utilizing React, Vite, and TypeScript, communicating with the backend
> routes from Problem 7. At a minimum it must: display all three tickets; let us
> select one and trigger the agent team to work it; visually present each agent,
> showing exactly what they are saying and doing while the ticket runs;
> automatically mark a ticket resolved once its run completes; display a brief
> summary of the actions each agent performed; provide a way for a human to
> approve a payment or purchase when agents request it; and show the current
> checking balance, visibly decreasing after a payment is approved. The dashboard
> must look professional and aesthetically pleasing — a realistic, well-thought-out
> workspace that humans would genuinely enjoy sitting at.
>
> *[Panel B]* Configure the frontend to call `http://localhost:8000` and set up
> CORS on the backend for the Vite origin `http://localhost:5173`. Launch with
> `npm run dev`. Finally, write `output/design.md` explaining our design choices —
> layout structure, how we visually distinguished the different agents' text, how
> resolved tickets and the cash balance are presented — and the reasoning behind
> them, including the creative decisions that give the interface a special,
> user-friendly feel.

### How it was carried out

Scaffolded Vite + React + TypeScript in `frontend/` and built a three-column
operator desk, ordered the way work flows: **the board** (tickets) → **the agent
floor** (live feed) → **your desk** (cash, approvals, recap). Nothing requiring
human action appears in the middle column, so the right edge is the only place
the operator has to watch.

The core legibility problem was five agents talking in one feed, solved by
giving **each agent an owned colour** used on its avatar, its name, its roster
chip and its recap card, and by rendering *speech* (prose) differently from
*action* (monospace tool pills) and *handoffs* (pink chips naming the target in
that agent's colour). Tool results are logged but not rendered — they would bury
the conversation, and the raw payloads remain in the audit trail.

Verified live by driving the real UI rather than trusting the code: clicked
**Reset shop**, selected ticket 101, clicked **Hand to the agent team**, watched
the feed stream Boss → Inventory → Accounting, then clicked **Approve**. Cash
moved **$3,400.00 → $2,560.00**, rendered in pink with a `−$840.00 just now`
delta, the approval card flipped to "✓ Approved by Yunsik Jung", and the toast
confirmed the payment. Run cost: 11 model calls, 9 tool calls, 29,338 tokens.

Wrote `output/design.md` covering the layout rationale, the agent colour system,
speech-vs-action rendering, how resolved tickets and the cash balance are
presented, the black-and-pink restraint, and the polling choice.

### Follow-up prompt — two fixes found by actually using it

*What the first build failed to achieve:* driving the real UI exposed two
problems the code looked fine for. First, the activity feed replayed **every run
ever recorded**, because the audit trail is append-only across the whole project
— on load it now shows only the most recent run. Second, the board only
refreshed on mount and after actions, so a single transient fetch failure left
the header reading "offline" permanently; it now refreshes on every idle poll
and heals itself.

One deliberate deviation from Panel A worth recording: the brief says to mark a
ticket resolved once the run completes, and the dashboard does update the status
automatically from the backend — but it shows the agents' **real** verdict rather
than forcing "resolved". Ticket 101 correctly ended **blocked**, because the tee
cannot ship until a human approves the $840 invoice holding the vendor. Painting
that green would tell the operator a customer is getting an order that is not
coming.

---

## Problem 9 — Resolve the tickets (10 points)

### Initial prompt

> **Problem 9: Resolve the tickets (10 points)**
>
> *[Panel A]* Before executing a full test run across the three tickets, reset
> the working database and note the initial checking balance. Then run all three
> tickets (101, 102, 103) until they are completely resolved. Open the
> `output/desk_tickets.html` from Problem 6 and fill out the "Actual" section for
> every ticket tab — which agents were active, the tasks they delegated, and the
> tools they used — leaving the original "Expected" intact for comparison.
>
> *[Panel B]* In the "Cash" tab, itemize the cash flow: the starting balance
> post-reset, how the balance changed on each ticket with the specific reasoning
> and exact dollar amounts, and the ending balance, which must perfectly match
> the `cash_accounts` table. Incorrect cash calculations lose points regardless
> of whether the board shows every ticket resolved. Also generate
> `output/resolved_tickets.json` (each ticket's ID, final status, outcome
> summary, each agent's contributions, and required human approvals) and
> `output/resolved_board.html` (an openable page with dashboard screenshots for
> all three resolved tickets). Finally, append these runs' logs to
> `output/audit_trail.json` and finalize `output/harness.md` so it covers the
> database tables, MCP tools, all five agents, the API routes, the dashboard and
> the safety rules.

### How it was carried out

Wrote `scripts/full_run.py` to drive the board through the live backend, so the
dashboard showed everything as it happened. It resets, runs each ticket, records
the supervisor's approvals, and re-runs — which is necessary, because a purchase
order cannot even be *requested* from a vendor holding an unpaid invoice, so
ticket 101 genuinely needs a human approval in the middle of it.

**Result: 3 / 3 resolved.** Cash $3,400.00 → $152.00, reconciling exactly with
`cash_accounts`: −$840.00 invoice 501, −$8.00 tee purchase order, −$2,400.00
rent, −$0.00 price override. The `payments` table holds exactly three rows, each
stamped `approved_by = "Yunsik Jung"`.

Filled all three Actual sections in `desk_tickets.html` from the audit trail
(agents, delegations and per-agent tool counts), wrote the itemised Cash tab,
and produced `resolved_tickets.json`, `resolved_board.html` with three dashboard
screenshots, and sections 12–13 of `harness.md`.

### Follow-up prompts — four things the first full run exposed

*What the first run failed to achieve:* it ended **2 / 3**, with ticket 103 stuck.

1. **Ticket 103 could not be resolved at all, and the agents were right.** They
   kept it `blocked`, insisting a price override needed supervisor authorisation
   — which it does, and which I had not built. The approval queue only handled
   payments and purchase orders. Added a `request_price_override` MCP tool that
   routes a discount through the same human-approval queue while moving no cash,
   plus a branch in `supervisor_resolve_approval` that authorises it without
   touching the balance.
2. **The Boss closed tickets without anyone replying to the requester**, and
   treated "we cannot afford all of it" as a blocker rather than a decision. Both
   fixed in `boss.md`; 103 then resolved in a single pass.
3. **`MAX_OUTPUT_TOKENS = 1_400` was too tight** — one run died with "Model token
   limit (1400) exceeded before any response was generated", wasting 45k tokens.
   Raised to 3,000.
4. **The cash ledger was being accumulated in the script and double-counted the
   rent across resumed runs.** Rewrote it to derive every movement from the
   `approvals` table and assert `reconciles_with_database`, so the recorded cash
   history cannot drift from the database — which is exactly what Panel B
   penalises.

Two Windows-specific bugs also surfaced: the console is `cp949` and crashed on
Unicode output mid-run (after the approval POST had already succeeded), and an
argparse patch silently failed to apply, causing an unintended reset. Both are
fixed, and `full_run.py` now supports `--tickets` and `--no-reset` so a run can
be resumed without re-spending tokens on tickets that are already done.

---

## Problem 10 — Reflection (10 points)

### Initial prompt

> 아래는 10번 문제고, 문제 진행하기 전에 우리가 어떤 것들을 해 왔는지 그리고 10번은 어떻게
> 작성하면 좋을지 자세하고 쉬운 가이드라인을 부탁해.
>
> **Problem 10: Reflection (10 points)**
>
> We need to open our `output/desk_tickets.html` file and thoroughly fill out the
> **Reflection** tab. It is absolutely critical that we tie every single answer
> directly to our specific application and the three tickets we just executed. We
> must actively use the data from our ticket tabs and the Cash tab as concrete
> evidence to support our reflections. If we generate generic AI essays that lack
> specific details about Campus Customs and our actual run, we will receive a low
> score. Please provide detailed and thorough answers to the following questions
> in our own words:
> - How do we evaluate the performance of our agents on each individual ticket,
>   and what is the reasoning behind our evaluation?
> - For every ticket, exactly how did the Actual execution compare to the
>   Expected plan we wrote earlier?
> - Looking back, what specific tasks would have been simpler to handle using
>   just a single agent equipped with tools—and why?
> - Describe three completely *new* problems that Campus Customs might face
>   which our current agent team could successfully solve using the tools we
>   have already built.
> - Describe three *new* problems that Campus Customs might face which our
>   current agent team could *not* solve. For these, explain exactly what new
>   tools and agents we would need to implement in order to resolve them.

### How it was carried out

Before writing anything, re-read the actual evidence rather than reasoning in the
abstract: the Expected/Actual sections and prediction-check callouts already
written into all three ticket tabs of `desk_tickets.html`, the Cash tab's
itemized ledger, `output/harness.md`'s MCP tool table, and `AI_prompts.md`'s own
record of problems 6 and 9. Two claims used in the answers were verified against
the live database rather than assumed: that `vendors` holds exactly three rows
with three distinct `specialty` values (so Bulldog Print Co really is the only
apparel vendor, which grounds the "no alternate supplier" answer), and the exact
`payments`/`cash_accounts` state matches what the Cash tab already reports.

Replaced the placeholder Reflection tab with five sections, one per question,
each citing specific ticket numbers, dollar amounts, tool names and pass counts
rather than generic statements:

1. **Evaluation criteria** — first contact correctness, exclusion of irrelevant
   agents, exact policy-number compliance ($36.67 margin floor, $2,400.00 rent),
   honest pending-vs-paid reporting, and pass count *attributed correctly*
   (ticket 103's 8 passes were a missing-tool problem, not a reasoning failure —
   provable because adding `request_price_override` and fixing `boss.md` made it
   resolve in one pass afterward).
2. **Actual vs. Expected** — a three-row table naming exactly what matched (101's
   refused purchase order, 102 matching in full, 103's commercial outcome) and
   what diverged (101's customer-service handoff came from Inventory sideways
   rather than the Boss; 103 needed a new tool before it could resolve at all).
3. **Single-agent case** — argued for ticket 102 by name, using its own "shortest
   chain" characterization from `harness.md` and its exact cost (11 requests, 10
   tool calls), plus the narrower claim that `check_inventory`'s role in ticket
   101 is a lookup rather than a judgment call.
4. **Three new solvable problems** — an in-stock order (unlike 101's), a second
   vendor's overdue invoice (generalizing 102), and a discount that clears the
   margin floor outright (the side of `quote_discount` ticket 103 never showed).
5. **Three new unsolvable problems** — a refund/deposit (cash only modeled as
   outgoing, confirmed in `harness.md`), a message that must actually be sent
   (`draft_message` has no send path by design), and an alternate-vendor
   substitution (confirmed against the live `vendors` table: one vendor per
   specialty, no fallback) — each paired with the specific new table, tool or
   role it would take to fix.

*No follow-up prompt was needed for this problem.*

---

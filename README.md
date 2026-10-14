# Campus Customs — Multi-Agent Shop Operations

Five AI agents (Boss, Inventory, Accounting, Facilities, Customer Service) work a
board of shop tickets for a campus merch store, through an MCP server that is
the only component with write access to the database. A human supervisor
approves every payment and purchase order from a React dashboard before any
cash actually moves.

Built for a Yale AI Foundations assignment. The full design rationale, every
database table and MCP tool, the agent prompts' reasoning, the dashboard's
visual choices, and the ten safety guardrails are documented in
[`output/harness.md`](output/harness.md) and [`output/design.md`](output/design.md).
The complete log of every prompt given to the vibe coder is in
[`AI_prompts.md`](AI_prompts.md). Expected-vs-actual predictions for the three
tickets, the itemized cash ledger, and a reflection on the whole project are in
[`output/desk_tickets.html`](output/desk_tickets.html) (open it directly in a
browser).

---

## 1. Clone and install

```bash
git clone <this-repo-url>
cd hw5
```

**Python** (3.11+). Create a virtual environment named `.venv` in the project
root and install from `requirements.txt`:

```bash
python -m venv .venv

# Windows
.venv\Scripts\python.exe -m pip install -r requirements.txt
# macOS / Linux
.venv/bin/python -m pip install -r requirements.txt
```

**Node** (18+), for the dashboard:

```bash
npm install --prefix frontend
```

## 2. Set up your `.env`

Copy the example file and fill in your own Portkey key:

```bash
cp .env.example .env
```

```ini
PORTKEY_API_KEY=your-key-here
```

`.env` is gitignored on purpose — never commit a real key. `backend/config.py`
reads it from this repo root (and, as a fallback, from the parent of wherever
you cloned this repo, which only matters if you keep several of this course's
projects side by side and share one key across them).

## 3. The database — original vs. working copy

`data/campus_customs.db` is the **pristine** database, extracted once from the
assignment's `data.zip` and never written to. `data/campus_customs_new.db` is
the **working copy** — the MCP server and the backend both point at this file,
and every tool call that changes shop state lands here.

To copy the original over the working copy (a clean reset), either call the
backend's reset route once it is running (see §4.3):

```bash
curl -X POST http://localhost:8000/api/reset
```

or run the same reset function directly without starting anything else:

```bash
.venv/Scripts/python.exe -c "from shop_db import reset_working_db; reset_working_db()"
```

Both do the same thing: fold any leftover write-ahead log back in, delete the
`-wal`/`-shm` sidecar files, copy `campus_customs.db` over
`campus_customs_new.db`, and re-apply the four tables this project adds
(`approvals`, `purchase_orders`, `drafts`, `activity_log`). The checking
balance goes back to **$3,400.00** and every ticket back to `open`.

**Always reset before a full three-ticket run** (§6) — resolving all three
tickets spends real (simulated) cash and leaves them `resolved`, so re-running
without resetting first will not reproduce the original scenario.

## 4. Run the three processes, in this order

Open three terminals at the repository root.

### 4.1 — MCP server (the only writer to the database)

```bash
.venv/Scripts/python.exe -m mcp_server.server --port 8787
```

Serves Streamable HTTP at `http://127.0.0.1:8787/mcp`. Must be running before
the backend, since every shop fact the backend serves is fetched through this
server.

### 4.2 — FastAPI backend (the agent team)

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Serves `http://localhost:8000`. CORS is enabled for the Vite dev origin
(`http://localhost:5173`). Confirm it's wired up correctly:

```bash
curl http://localhost:8000/api/health
```

should report the model (`gpt-6-luna`) and that the MCP server is reachable.

### 4.3 — React dashboard (the operator desk)

```bash
npm run dev --prefix frontend
```

Open `http://localhost:5173`. Click **Reset shop**, pick a ticket, and **Hand
to the agent team** — the feed streams every agent's messages, tool calls and
delegations live, and the approval queue is where you, the human supervisor,
click Approve or Deny on anything that spends money.

## 5. Connecting the MCP server to a vibe coder (e.g. Claude Code)

`.mcp.json` at the repo root already registers the server as a local stdio
subprocess:

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

Restart your coding assistant after cloning so it picks this up. See
[`mcp_server/README.md`](mcp_server/README.md) for the full tool list.

## 6. Running a complete three-ticket resolution from the command line

With the MCP server, backend and dashboard all already running (§4), reset the
database (§3) and then:

```bash
.venv/Scripts/python.exe -m scripts.full_run
```

This drives tickets 101, 102 and 103 through the live backend one at a time,
recording each human approval along the way (a purchase order cannot even be
*requested* from a vendor holding an unpaid invoice, so ticket 101 genuinely
needs an approval mid-run). It writes `output/resolved_tickets.json` and
appends to `output/audit_trail.json` — append-only, so it is never wiped by a
later run. Pass `--tickets 103` to run a single ticket, or `--no-reset` to
resume a run without re-spending tokens on tickets already resolved.

## 7. Project layout

```
.
├── backend/            FastAPI app, the 5 PydanticAI agents, prompts/, config
├── mcp_server/          FastMCP server -- the only writer to the database
├── shop_db/             SQLite connection handling, schema, reset
├── frontend/             React + Vite + TypeScript dashboard
├── scripts/             full_run.py, mcp_smoke.py, run_board.py
├── data/
│   ├── campus_customs.db       pristine -- never written to
│   └── campus_customs_new.db   working copy -- every mutation lands here
└── output/              harness.md, design.md, desk_tickets.html,
                         resolved_tickets.json, resolved_board.html,
                         audit_trail.json, mcp_smoke.json, github_url.txt
```

## 8. Safety

No agent can execute a payment or purchase order — those tools only ever write
a `pending` row to an approvals queue; execution is a separate tool blocked
from every agent's toolset and gated behind a human clicking Approve in the
dashboard. `draft_message` has no send path anywhere in the codebase, so no
real email or vendor call is ever possible. Full list of guardrails, and what
is deliberately *not* guarded yet, in [`output/harness.md` §10](output/harness.md).

"""FastAPI backend for the Campus Customs dashboard.

Start it from inside the backend/ directory:

    uvicorn main:app --reload --port 8000

The MCP server must already be running, since every shop fact served here is
fetched through it:

    .venv/Scripts/python.exe -m mcp_server.server --port 8787
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow `uvicorn main:app` from inside backend/ as well as `backend.main` from
# the project root -- both need the repository root on sys.path.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from backend.agents import build_team  # noqa: E402
from backend.audit import AuditTrail  # noqa: E402
from backend.config import AUDIT_TRAIL, DEFAULT_SUPERVISOR, MCP_URL, MODEL_ID  # noqa: E402
from backend.models import RunSummary  # noqa: E402
from backend.runner import run_board  # noqa: E402
from backend import shop as shop_api  # noqa: E402
from shop_db import reset_working_db  # noqa: E402


# --------------------------------------------------------------------------
# Request / response bodies
# --------------------------------------------------------------------------
class ApprovalBody(BaseModel):
    decision: str = Field(description="'approve' or 'deny'")
    approver: str = Field(default=DEFAULT_SUPERVISOR)
    note: str | None = None


class RunBody(BaseModel):
    supervisor: str = Field(default=DEFAULT_SUPERVISOR)
    wait: bool = Field(default=False, description="block until the run finishes")


# --------------------------------------------------------------------------
# Runtime state
# --------------------------------------------------------------------------
class Runtime:
    """Holds the agent team and tracks runs so only one happens at a time."""

    def __init__(self) -> None:
        self.team = None
        self.lock = asyncio.Lock()
        self.runs: dict[str, dict[str, Any]] = {}
        self.active_run_id: str | None = None

    def get_team(self):
        if self.team is None:
            self.team = build_team()
        return self.team


runtime = Runtime()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await shop_api.shop.connect()
    yield
    await shop_api.shop.close()


app = FastAPI(
    title="Campus Customs Operations",
    description="Backend for the multi-agent shop dashboard.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_audit() -> list[dict[str, Any]]:
    """The audit trail is our own output file, not shop data."""
    if not AUDIT_TRAIL.exists():
        return []
    try:
        data = json.loads(AUDIT_TRAIL.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []
    return data if isinstance(data, list) else []


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------
@app.get("/api/health", summary="Service health and whether the MCP server is reachable")
async def health() -> dict[str, Any]:
    try:
        await shop_api.shop.call("get_policies")
        mcp_ok = True
        error = None
    except Exception as exc:
        mcp_ok = False
        error = str(exc)
    return {
        "ok": mcp_ok,
        "model": MODEL_ID,
        "mcp_url": MCP_URL,
        "mcp_reachable": mcp_ok,
        "mcp_error": error,
        "run_active": runtime.active_run_id,
    }


# --------------------------------------------------------------------------
# Tickets
# --------------------------------------------------------------------------
@app.get("/api/tickets", summary="The three tickets and whether each is open or resolved")
async def get_tickets() -> dict[str, Any]:
    tickets = await shop_api.all_tickets()
    for ticket in tickets:
        ticket["is_open"] = ticket.get("status") not in ("resolved", "closed")
    return {
        "tickets": tickets,
        "open_count": sum(1 for t in tickets if t["is_open"]),
        "resolved_count": sum(1 for t in tickets if not t["is_open"]),
    }


@app.get("/api/tickets/{ticket_id}", summary="One ticket with its linked invoice, lease and stock")
async def get_ticket(ticket_id: int) -> dict[str, Any]:
    result = await shop_api.shop.call("get_ticket", {"ticket_id": ticket_id})
    if not result.get("ok"):
        raise HTTPException(404, result.get("error", "Ticket not found"))
    return result


async def _execute_run(run_id: str, ticket_id: int, supervisor: str) -> None:
    """Run the agent team over one ticket and record the outcome."""
    audit = AuditTrail(run_id)
    try:
        summary = await run_board(
            ticket_ids=[ticket_id],
            supervisor=supervisor,
            audit=audit,
            team=runtime.get_team(),
            run_id=run_id,
        )
        runtime.runs[run_id].update(
            status="finished", finished_at=_now(), summary=summary.model_dump()
        )
    except Exception as exc:
        audit.record(
            kind="error", ticket_id=ticket_id, summary=f"Run failed: {exc}",
            detail={"error": str(exc), "type": type(exc).__name__},
        )
        runtime.runs[run_id].update(
            status="failed", finished_at=_now(), error=f"{type(exc).__name__}: {exc}"
        )
    finally:
        runtime.active_run_id = None
        if runtime.lock.locked():
            runtime.lock.release()


@app.post(
    "/api/tickets/{ticket_id}/run",
    summary="Hand a ticket to the agent team",
    status_code=202,
)
async def run_ticket(
    ticket_id: int, body: RunBody | None = None, background: BackgroundTasks = None
) -> dict[str, Any]:
    body = body or RunBody()

    if not await shop_api.ticket_row(ticket_id):
        raise HTTPException(404, f"No ticket with id {ticket_id}.")
    if runtime.active_run_id:
        raise HTTPException(
            409, f"Run {runtime.active_run_id} is already in progress. Wait for it to finish."
        )

    await runtime.lock.acquire()
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    runtime.active_run_id = run_id
    runtime.runs[run_id] = {
        "run_id": run_id,
        "ticket_id": ticket_id,
        "status": "running",
        "started_at": _now(),
        "audit_cursor": len(_read_audit()),
    }

    if body.wait:
        await _execute_run(run_id, ticket_id, body.supervisor)
        return runtime.runs[run_id]

    background.add_task(_execute_run, run_id, ticket_id, body.supervisor)
    return runtime.runs[run_id]


@app.get("/api/runs/{run_id}", summary="Status and result of one agent run")
async def get_run(run_id: str) -> dict[str, Any]:
    run = runtime.runs.get(run_id)
    if not run:
        raise HTTPException(404, f"No run with id {run_id}.")
    return run


@app.get("/api/runs", summary="All agent runs this process has started")
async def list_runs() -> dict[str, Any]:
    return {"runs": list(runtime.runs.values()), "active": runtime.active_run_id}


# --------------------------------------------------------------------------
# Activity feed
# --------------------------------------------------------------------------
@app.get(
    "/api/activity",
    summary="Latest agent activity: what each agent said and which tools it used",
)
async def activity(
    after: int = Query(0, ge=0, description="return events after this index"),
    limit: int = Query(300, ge=1, le=2000),
    run_id: str | None = None,
) -> dict[str, Any]:
    events = _read_audit()
    total = len(events)
    window = events[after:]
    if run_id:
        window = [e for e in window if e.get("run_id") == run_id]
    window = window[:limit]
    return {
        "events": window,
        "cursor": min(after + limit, total),
        "total": total,
        "run_active": runtime.active_run_id,
    }


# --------------------------------------------------------------------------
# Money
# --------------------------------------------------------------------------
@app.get("/api/cash", summary="Current checking balance from the cash_accounts table")
async def cash() -> dict[str, Any]:
    return await shop_api.shop.call("get_cash")


@app.get("/api/approvals", summary="Payment and purchase-order requests awaiting a human")
async def approvals(status: str | None = None) -> dict[str, Any]:
    rows = await shop_api.approval_rows(status)
    for row in rows:
        for field in ("payload", "result"):
            if isinstance(row.get(field), str):
                try:
                    row[field] = json.loads(row[field])
                except (json.JSONDecodeError, TypeError):
                    pass
    return {"approvals": rows, "pending": sum(1 for r in rows if r["status"] == "pending")}


@app.post(
    "/api/approvals/{approval_id}/decision",
    summary="Record the supervisor's approve/deny -- the only route that moves cash",
)
async def decide_approval(approval_id: int, body: ApprovalBody) -> dict[str, Any]:
    if body.decision not in ("approve", "deny"):
        raise HTTPException(400, "decision must be 'approve' or 'deny'")

    before = await shop_api.cash_balance()
    result = await shop_api.resolve_approval(
        approval_id, body.decision, body.approver, body.note
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Could not resolve the approval."))

    after = await shop_api.cash_balance()
    AuditTrail(runtime.active_run_id or "supervisor").record(
        kind="approval_resolved",
        agent="supervisor",
        summary=result.get("message", f"Approval {approval_id} {body.decision}d"),
        detail={
            "approval_id": approval_id,
            "approver": body.approver,
            "cash_before": before,
            "cash_after": after,
            "result": result.get("result"),
        },
    )
    return {**result, "cash_before": before, "cash_after": after}


@app.get("/api/payment-plan", summary="Cash against every obligation, for prioritising")
async def payment_plan() -> dict[str, Any]:
    return await shop_api.payment_plan()


# --------------------------------------------------------------------------
# Board snapshot for the dashboard
# --------------------------------------------------------------------------
@app.get("/api/board", summary="Full shop snapshot in one call")
async def board() -> dict[str, Any]:
    overview = await shop_api.overview()
    return {
        "date_today": overview.get("date_today"),
        "cash": overview.get("cash_balance"),
        "tickets": await shop_api.all_tickets(),
        "inventory": await shop_api.inventory_rows(),
        "invoices": await shop_api.invoice_rows(),
        "leases": await shop_api.lease_rows(),
        "payments": await shop_api.payment_rows(),
        "purchase_orders": await shop_api.purchase_order_rows(),
        "drafts": await shop_api.draft_rows(),
        "notes": await shop_api.board_notes(),
        "approvals": await shop_api.approval_rows(),
    }


@app.get("/api/drafts", summary="Customer message drafts on the board -- never sent")
async def drafts() -> dict[str, Any]:
    return {"drafts": await shop_api.draft_rows()}


# --------------------------------------------------------------------------
# Reset
# --------------------------------------------------------------------------
@app.post("/api/reset", summary="Restore the database to its initial state for a fresh run")
async def reset() -> dict[str, Any]:
    if runtime.active_run_id:
        raise HTTPException(409, "A run is in progress; let it finish before resetting.")
    path = reset_working_db()
    return {
        "ok": True,
        "database": path.name,
        "message": "Working database restored from the pristine data/campus_customs.db.",
        "cash": await shop_api.cash_balance(),
    }

"""Runs the agent team over the ticket board."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable

from pydantic_ai.usage import RunUsage as PydanticRunUsage

from backend.agents import Team, build_team, ticket_usage_limits
from backend.audit import AuditTrail
from backend.config import DEFAULT_SUPERVISOR, MODEL_ID
from backend.models import (
    AgentName,
    RunSummary,
    RunUsage,
    ShopDeps,
    TicketResult,
)
from backend.shop import (
    approval_rows,
    cash_balance,
    open_tickets,
    resolve_approval,
    ticket_row,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _usage(src: PydanticRunUsage) -> RunUsage:
    return RunUsage(
        requests=src.requests,
        tool_calls=src.tool_calls,
        input_tokens=src.input_tokens,
        output_tokens=src.output_tokens,
        total_tokens=src.input_tokens + src.output_tokens,
    )


BOSS_BRIEF = """Ticket {ticket_id} is on the board.

Subject: {subject}
Type: {type}
From: {requester}
Notes: {notes}

Work this ticket to a decision. Read it, assign it, delegate to the specialist
whose job it actually is, and close it out with update_ticket. Only involve the
agents who have something to contribute."""


async def run_ticket(
    team: Team,
    ticket_id: int,
    audit: AuditTrail,
    supervisor: str = DEFAULT_SUPERVISOR,
) -> TicketResult:
    """Put one ticket through the Boss and the specialists it pulls in."""
    ticket = await ticket_row(ticket_id)
    if ticket is None:
        return TicketResult(ticket_id=ticket_id, subject="", error="No such ticket.")

    audit.record(
        kind="ticket_started",
        agent=AgentName.BOSS.value,
        ticket_id=ticket_id,
        summary=f"Ticket {ticket_id}: {ticket['subject']} ({ticket['type']})",
        detail={"ticket": ticket},
    )

    deps = ShopDeps(
        run_id=audit.run_id,
        ticket_id=ticket_id,
        supervisor=supervisor,
        agent=AgentName.BOSS.value,
        call_stack=[AgentName.BOSS.value],
        audit=audit,
    )
    usage = PydanticRunUsage()

    try:
        result = await team.boss.run(
            BOSS_BRIEF.format(
                ticket_id=ticket_id,
                subject=ticket["subject"],
                type=ticket["type"],
                requester=ticket["requester"],
                notes=ticket.get("notes") or "(none)",
            ),
            deps=deps,
            usage=usage,
            usage_limits=ticket_usage_limits(),
        )
    except Exception as exc:  # a limit hit or a model error ends this ticket only
        audit.record(
            kind="error",
            agent=AgentName.BOSS.value,
            ticket_id=ticket_id,
            summary=f"Ticket {ticket_id} failed: {exc}",
            detail={"error": str(exc), "type": type(exc).__name__},
        )
        return TicketResult(
            ticket_id=ticket_id,
            subject=ticket["subject"],
            error=f"{type(exc).__name__}: {exc}",
            usage=_usage(usage),
        )

    decision = result.output
    audit.record(
        kind="ticket_finished",
        agent=AgentName.BOSS.value,
        ticket_id=ticket_id,
        summary=decision.decision,
        model=MODEL_ID,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.input_tokens + usage.output_tokens,
        detail=decision.model_dump(),
    )
    return TicketResult(
        ticket_id=ticket_id,
        subject=ticket["subject"],
        decision=decision,
        usage=_usage(usage),
    )


async def run_board(
    ticket_ids: Iterable[int] | None = None,
    supervisor: str = DEFAULT_SUPERVISOR,
    audit: AuditTrail | None = None,
    team: Team | None = None,
    run_id: str | None = None,
) -> RunSummary:
    """Work every open ticket on the board, one at a time."""
    run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
    audit = audit or AuditTrail(run_id)
    team = team or build_team()

    ids = list(ticket_ids) if ticket_ids is not None else [t["id"] for t in await open_tickets()]
    summary = RunSummary(
        run_id=run_id,
        started_at=_now(),
        model=MODEL_ID,
        supervisor=supervisor,
        cash_before=await cash_balance(),
    )

    audit.record(
        kind="run_started",
        summary=f"Run {run_id} over tickets {ids}",
        model=MODEL_ID,
        detail={"tickets": ids, "supervisor": supervisor, "cash": summary.cash_before},
    )

    async with team.toolset:
        for ticket_id in ids:
            result = await run_ticket(team, ticket_id, audit, supervisor)
            summary.tickets.append(result)
            summary.usage.requests += result.usage.requests
            summary.usage.tool_calls += result.usage.tool_calls
            summary.usage.input_tokens += result.usage.input_tokens
            summary.usage.output_tokens += result.usage.output_tokens
            summary.usage.total_tokens += result.usage.total_tokens

    summary.finished_at = _now()
    summary.cash_after = await cash_balance()
    audit.record(
        kind="run_finished",
        summary=(
            f"Run {run_id} finished: {len(summary.tickets)} ticket(s), "
            f"{summary.usage.total_tokens:,} tokens, "
            f"{len(await approval_rows('pending'))} approval(s) pending"
        ),
        model=MODEL_ID,
        input_tokens=summary.usage.input_tokens,
        output_tokens=summary.usage.output_tokens,
        total_tokens=summary.usage.total_tokens,
        detail=summary.model_dump(),
    )
    return summary


async def approve(
    approval_id: int,
    decision: str,
    approver: str = DEFAULT_SUPERVISOR,
    note: str | None = None,
    audit: AuditTrail | None = None,
) -> dict:
    """Record the human's decision. This is the only path that moves money."""
    result = await resolve_approval(approval_id, decision, approver, note)
    if audit:
        audit.record(
            kind="approval_resolved",
            agent="supervisor",
            summary=result.get("message", f"Approval {approval_id} {decision}d"),
            detail=result,
        )
    return result

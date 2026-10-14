"""All data types for the Campus Customs agent backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentName(str, Enum):
    """The five roles on the Campus Customs team."""

    BOSS = "boss"
    INVENTORY = "inventory"
    ACCOUNTING = "accounting"
    FACILITIES = "facilities"
    CUSTOMER_SERVICE = "customer_service"


SPECIALISTS = [
    AgentName.INVENTORY,
    AgentName.ACCOUNTING,
    AgentName.FACILITIES,
    AgentName.CUSTOMER_SERVICE,
]

TicketStatus = Literal["open", "in_progress", "blocked", "resolved"]


# --------------------------------------------------------------------------
# Agent outputs
# --------------------------------------------------------------------------
class AgentReport(BaseModel):
    """What a specialist hands back to whoever delegated to it."""

    summary: str = Field(description="What was found or done, in two or three sentences.")
    findings: list[str] = Field(
        default_factory=list,
        description="Concrete facts pulled from the shop database, each with its numbers.",
    )
    actions_taken: list[str] = Field(
        default_factory=list, description="Tool calls that changed shop state."
    )
    blocked_by: str | None = Field(
        default=None,
        description="What stops this from being finished, if anything -- e.g. an unpaid invoice or a pending approval.",
    )
    recommendation: str = Field(
        description="What the delegating agent should do next, stated plainly."
    )


class TicketDecision(BaseModel):
    """The Boss's final call on one ticket."""

    ticket_id: int
    status: TicketStatus = Field(description="Where the ticket ends up after this run.")
    decision: str = Field(description="The decision made, in the Boss's own words.")
    reasoning: str = Field(description="Why this is the right call given cash, stock and the shop rules.")
    agents_consulted: list[str] = Field(default_factory=list)
    awaiting_approval: list[int] = Field(
        default_factory=list, description="Approval ids this ticket is waiting on."
    )
    customer_message_drafted: bool = False


# --------------------------------------------------------------------------
# Delegation
# --------------------------------------------------------------------------
class DelegationResult(BaseModel):
    """The envelope returned to an agent when it delegates to a teammate."""

    delegated_to: str
    accepted: bool = True
    report: AgentReport | None = None
    error: str | None = None


# --------------------------------------------------------------------------
# Approvals
# --------------------------------------------------------------------------
ApprovalStatus = Literal["pending", "approved", "denied", "failed"]


class ApprovalRequest(BaseModel):
    id: int
    kind: str
    ref_id: int | None = None
    ticket_id: int | None = None
    amount: float
    account: str
    memo: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    status: ApprovalStatus
    requested_by: str
    requested_at: str
    decided_by: str | None = None
    decided_at: str | None = None
    decision_note: str | None = None
    result: dict[str, Any] | None = None


class ApprovalDecision(BaseModel):
    """What the human supervisor sends back from the dashboard."""

    decision: Literal["approve", "deny"]
    approver: str
    note: str | None = None


# --------------------------------------------------------------------------
# Audit trail
# --------------------------------------------------------------------------
EventKind = Literal[
    "run_started",
    "run_finished",
    "ticket_started",
    "ticket_finished",
    "agent_started",
    "agent_finished",
    "delegation",
    "delegation_refused",
    "tool_call",
    "tool_result",
    "model_request",
    "approval_requested",
    "approval_resolved",
    "limit_reached",
    "error",
]


class AuditEvent(BaseModel):
    """One appended line of the execution log."""

    run_id: str
    seq: int
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    kind: EventKind
    agent: str | None = None
    ticket_id: int | None = None
    depth: int = 0
    summary: str = ""
    tool: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: Any | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    detail: dict[str, Any] | None = None


# --------------------------------------------------------------------------
# Run bookkeeping
# --------------------------------------------------------------------------
class RunUsage(BaseModel):
    requests: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class TicketResult(BaseModel):
    ticket_id: int
    subject: str
    decision: TicketDecision | None = None
    error: str | None = None
    usage: RunUsage = Field(default_factory=RunUsage)


class RunSummary(BaseModel):
    run_id: str
    started_at: str
    finished_at: str | None = None
    model: str
    supervisor: str
    tickets: list[TicketResult] = Field(default_factory=list)
    usage: RunUsage = Field(default_factory=RunUsage)
    cash_before: float | None = None
    cash_after: float | None = None
    error: str | None = None


# --------------------------------------------------------------------------
# Dependencies carried through every agent run
# --------------------------------------------------------------------------
@dataclass
class ShopDeps:
    """Shared state threaded through the whole delegation tree for one ticket."""

    run_id: str
    ticket_id: int | None = None
    supervisor: str = "supervisor"
    depth: int = 0
    # Agents currently on the call stack, used to refuse delegation cycles.
    call_stack: list[str] = field(default_factory=list)
    tool_calls: int = 0
    # The run's AuditTrail.  Typed loosely to keep models.py import-free.
    audit: Any = None
    agent: str = ""

    def child(self, agent: str) -> "ShopDeps":
        """Deps for a nested agent run, one level deeper."""
        return ShopDeps(
            run_id=self.run_id,
            ticket_id=self.ticket_id,
            supervisor=self.supervisor,
            depth=self.depth + 1,
            call_stack=[*self.call_stack, agent],
            tool_calls=self.tool_calls,
            audit=self.audit,
            agent=agent,
        )

"""The Campus Customs agent team, built with PydanticAI.

Five agents -- Boss, Inventory, Accounting, Facilities, Customer Service -- all
running on the single permitted model (``gpt-6-luna`` via Portkey) and all
reaching the shop exclusively through the MCP server.  There is no second data
path: if a fact is not available from an MCP tool, no agent has it.

The team is fully connected: every agent carries an ``ask_<agent>`` tool for
every other agent, so any of them can pull in any teammate.  Cycles and runaway
depth are stopped by the call stack carried in ``ShopDeps``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import CallToolFunc, MCPToolset, StreamableHttpTransport
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import UsageLimits

from backend.audit import AuditTrail
from backend.config import (
    AGENT_RETRIES,
    MAX_DELEGATION_DEPTH,
    MAX_OUTPUT_TOKENS,
    MAX_REQUESTS_PER_TICKET,
    MAX_TOOL_CALLS_PER_TICKET,
    MAX_TOTAL_TOKENS_PER_TICKET,
    MCP_URL,
    MODEL_ID,
    PORTKEY_BASE_URL,
    PROMPTS_DIR,
    SUPERVISOR_ONLY_TOOLS,
    portkey_api_key,
)
from backend.models import AgentName, AgentReport, DelegationResult, ShopDeps, TicketDecision

# --------------------------------------------------------------------------
# Which MCP tools each role is allowed to touch.
#
# Narrow allowlists are not only a safety measure -- a smaller tool schema is a
# smaller prompt on every single model call, which is the cheapest token saving
# available in a multi-agent system.
#
# `supervisor_resolve_approval` appears in no list.  It is the tool that moves
# money, and only the backend calls it, on behalf of a human.
# --------------------------------------------------------------------------
AGENT_TOOLS: dict[AgentName, set[str]] = {
    AgentName.BOSS: {
        "get_policies",
        "get_shop_overview",
        "list_tickets",
        "get_ticket",
        "assign_ticket",
        "update_ticket",
        "get_cash",
        "list_approvals",
        "get_approval",
        "post_board_note",
    },
    AgentName.INVENTORY: {
        "get_ticket",
        "check_inventory",
        "low_stock_report",
        "find_restock_options",
        "get_vendor_status",
        "list_vendors",
        "get_pricing",
        "reserve_stock",
        "request_purchase_order",
        "list_purchase_orders",
        "get_approval",
        "post_board_note",
    },
    AgentName.ACCOUNTING: {
        "get_ticket",
        "get_cash",
        "get_payment_plan",
        "list_invoices",
        "list_payments",
        "quote_discount",
        "get_pricing",
        "list_vendors",
        "get_vendor_status",
        "request_payment",
        "request_purchase_order",
        "request_price_override",
        "list_approvals",
        "get_approval",
        "post_board_note",
    },
    AgentName.FACILITIES: {
        "get_ticket",
        "get_shop_overview",
        "list_leases",
        "get_cash",
        "list_payments",
        "request_payment",
        "get_approval",
        "post_board_note",
    },
    AgentName.CUSTOMER_SERVICE: {
        "get_ticket",
        "draft_message",
        "list_drafts",
        "list_purchase_orders",
        "post_board_note",
    },
}

AGENT_DESCRIPTIONS: dict[AgentName, str] = {
    AgentName.BOSS: "Reviews tickets, routes them to the right specialist and makes the final call.",
    AgentName.INVENTORY: "Stock by SKU and size, shortages, vendor selection and restock timing.",
    AgentName.ACCOUNTING: "Cash, invoices, margins, and queuing payments and purchase orders for human approval.",
    AgentName.FACILITIES: "The shop space: leases, the landlord and rent.",
    AgentName.CUSTOMER_SERVICE: "Drafts replies to customers. Drafts only -- nothing is ever sent.",
}


def load_prompt(agent: AgentName) -> str:
    path = PROMPTS_DIR / f"{agent.value}.md"
    if not path.exists():
        raise FileNotFoundError(f"Missing prompt file for {agent.value}: {path}")
    return path.read_text(encoding="utf-8")


def build_model() -> OpenAIResponsesModel:
    """The one model every agent uses, routed through Portkey.

    gpt-6-luna rejects function tools on /v1/chat/completions, so the team runs
    on the Responses API.
    """
    return OpenAIResponsesModel(
        MODEL_ID,
        provider=OpenAIProvider(base_url=PORTKEY_BASE_URL, api_key=portkey_api_key()),
    )


def ticket_usage_limits() -> UsageLimits:
    """Hard ceilings for one ticket's entire delegation tree."""
    return UsageLimits(
        request_limit=MAX_REQUESTS_PER_TICKET,
        tool_calls_limit=MAX_TOOL_CALLS_PER_TICKET,
        total_tokens_limit=MAX_TOTAL_TOKENS_PER_TICKET,
    )


# --------------------------------------------------------------------------
# MCP wiring
# --------------------------------------------------------------------------
def _audit_tool_calls(
    ctx: RunContext[ShopDeps],
    call_tool: CallToolFunc,
    name: str,
    tool_args: dict[str, Any],
) -> Awaitable[Any]:
    """Log every MCP tool call to the audit trail, and hard-block the money tool."""

    async def run() -> Any:
        deps = ctx.deps
        audit: AuditTrail | None = getattr(deps, "audit", None)
        agent = deps.agent or "unknown"

        # Belt and braces: the toolset filter already hides this, but if a model
        # ever named it anyway, it must not reach the server.
        if name in SUPERVISOR_ONLY_TOOLS:
            message = (
                f"'{name}' is reserved for the human supervisor and cannot be "
                "called by an agent. Payments are executed only after a human "
                "approves them in the dashboard."
            )
            if audit:
                audit.record(
                    kind="error",
                    agent=agent,
                    ticket_id=deps.ticket_id,
                    depth=deps.depth,
                    tool=name,
                    summary=message,
                )
            raise PermissionError(message)

        if audit:
            audit.record(
                kind="tool_call",
                agent=agent,
                ticket_id=deps.ticket_id,
                depth=deps.depth,
                tool=name,
                tool_args=tool_args,
                summary=f"{agent} called {name}",
            )
        result = await call_tool(name, tool_args)
        if audit:
            audit.record(
                kind="tool_result",
                agent=agent,
                ticket_id=deps.ticket_id,
                depth=deps.depth,
                tool=name,
                tool_result=result,
                summary=f"{name} returned",
            )
            # Surface an approval request as its own event for the dashboard.
            payload = result if isinstance(result, dict) else None
            if payload and payload.get("status") == "pending_human_approval":
                audit.record(
                    kind="approval_requested",
                    agent=agent,
                    ticket_id=deps.ticket_id,
                    depth=deps.depth,
                    tool=name,
                    summary=payload.get("message", "Approval requested"),
                    detail={"approval_id": payload.get("approval_id")},
                )
        return result

    return run()


def build_toolset() -> MCPToolset:
    """One shared connection to the Campus Customs MCP server."""
    return MCPToolset(
        StreamableHttpTransport(url=MCP_URL),
        id="campus-customs",
        process_tool_call=_audit_tool_calls,
        # Tool schemas do not change mid-run; caching them avoids re-listing.
        cache_tools=True,
    )


def _toolset_for(toolset: MCPToolset, agent: AgentName) -> Any:
    allowed = AGENT_TOOLS[agent] - set(SUPERVISOR_ONLY_TOOLS)

    def _filter(ctx: RunContext[ShopDeps], tool_def: ToolDefinition) -> bool:
        return tool_def.name in allowed

    return toolset.filtered(_filter)


# --------------------------------------------------------------------------
# The team
# --------------------------------------------------------------------------
@dataclass
class Team:
    agents: dict[AgentName, Agent]
    toolset: MCPToolset

    def __getitem__(self, name: AgentName) -> Agent:
        return self.agents[name]

    @property
    def boss(self) -> Agent:
        return self.agents[AgentName.BOSS]


def _register_delegation(team_agents: dict[AgentName, Agent], me: AgentName) -> None:
    """Give `me` an ask_<agent> tool for every teammate -- the full mesh."""
    agent = team_agents[me]

    for other in AgentName:
        if other is me:
            continue

        def make_tool(target: AgentName) -> Callable[..., Any]:
            async def delegate(
                ctx: RunContext[ShopDeps], task: str, context: str = ""
            ) -> DelegationResult:
                deps = ctx.deps
                audit: AuditTrail | None = getattr(deps, "audit", None)
                target_name = target.value

                # Guard 1: depth.  Guard 2: no cycles back into an agent that is
                # already waiting higher up the stack.
                refusal: str | None = None
                if deps.depth >= MAX_DELEGATION_DEPTH:
                    refusal = (
                        f"Delegation depth limit ({MAX_DELEGATION_DEPTH}) reached; "
                        f"answer with what you already have instead of asking "
                        f"{target_name}."
                    )
                elif target_name in deps.call_stack:
                    refusal = (
                        f"{target_name} is already working further up this chain; "
                        "asking it again would loop. Use what it told you."
                    )

                if refusal:
                    if audit:
                        audit.record(
                            kind="delegation_refused",
                            agent=deps.agent or me.value,
                            ticket_id=deps.ticket_id,
                            depth=deps.depth,
                            summary=refusal,
                            detail={"target": target_name, "task": task},
                        )
                    return DelegationResult(
                        delegated_to=target_name, accepted=False, error=refusal
                    )

                if audit:
                    audit.record(
                        kind="delegation",
                        agent=deps.agent or me.value,
                        ticket_id=deps.ticket_id,
                        depth=deps.depth,
                        summary=f"{deps.agent or me.value} -> {target_name}: {task}",
                        detail={"target": target_name, "task": task, "context": context},
                    )

                child = deps.child(target_name)
                prompt = task if not context else f"{task}\n\nContext you were given:\n{context}"
                result = await team_agents[target].run(
                    prompt,
                    deps=child,
                    usage=ctx.usage,           # roll nested cost up into the ticket
                    usage_limits=ctx.usage_limits,
                )

                if audit:
                    audit.record(
                        kind="agent_finished",
                        agent=target_name,
                        ticket_id=deps.ticket_id,
                        depth=child.depth,
                        summary=result.output.summary,
                        detail=result.output.model_dump(),
                    )
                return DelegationResult(delegated_to=target_name, report=result.output)

            return delegate

        agent.tool(
            make_tool(other),
            name=f"ask_{other.value}",
            description=(
                f"Delegate to the {other.value} agent. {AGENT_DESCRIPTIONS[other]} "
                "Give it a specific task and any context you already have so it "
                "does not re-fetch what you know."
            ),
        )


def build_team(toolset: MCPToolset | None = None) -> Team:
    """Construct all five agents and wire the delegation mesh between them."""
    model = build_model()
    shared_toolset = toolset or build_toolset()
    settings = ModelSettings(max_tokens=MAX_OUTPUT_TOKENS)

    agents: dict[AgentName, Agent] = {}
    for name in AgentName:
        agents[name] = Agent(
            model,
            deps_type=ShopDeps,
            output_type=TicketDecision if name is AgentName.BOSS else AgentReport,
            instructions=load_prompt(name),
            toolsets=[_toolset_for(shared_toolset, name)],
            model_settings=settings,
            retries=AGENT_RETRIES,
            name=name.value,
        )

    for name in AgentName:
        _register_delegation(agents, name)

    return Team(agents=agents, toolset=shared_toolset)

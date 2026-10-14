import { useEffect, useRef, useState } from "react";
import type { Approval, AuditEvent, Cash, RunState } from "../types";
import { agentStyle } from "../agents";

const money = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD" });

/** Balance tile. Flashes and shows the delta whenever cash falls. */
export function CashCard({ cash }: { cash: Cash | null }) {
  const [delta, setDelta] = useState<number | null>(null);
  const [dropped, setDropped] = useState(false);
  const prev = useRef<number | null>(null);

  useEffect(() => {
    if (!cash) return;
    if (prev.current !== null && cash.balance !== prev.current) {
      const d = cash.balance - prev.current;
      setDelta(d);
      setDropped(d < 0);
      const timer = setTimeout(() => setDropped(false), 2200);
      return () => clearTimeout(timer);
    }
    prev.current = cash.balance;
  }, [cash?.balance]);

  useEffect(() => {
    if (cash) prev.current = cash.balance;
  }, [cash?.balance]);

  if (!cash) return null;

  return (
    <div className="cash-card">
      <div className="cash-label">Checking account</div>
      <div className={`cash-value ${dropped ? "dropped" : ""}`}>{money(cash.balance)}</div>
      <div className="cash-delta">
        {delta !== null && delta !== 0
          ? `${delta < 0 ? "−" : "+"}${money(Math.abs(delta)).replace("$", "$")} just now`
          : ""}
      </div>
      <div className="cash-sub">
        <span>
          Awaiting your approval <b>{money(cash.pending_approval_total)}</b>
        </span>
        <span>
          Free <b>{money(cash.uncommitted)}</b>
        </span>
      </div>
    </div>
  );
}

/** The human-in-the-loop queue. Nothing moves money except these buttons. */
export function ApprovalQueue({
  approvals,
  onDecide,
  busy,
}: {
  approvals: Approval[];
  onDecide: (id: number, d: "approve" | "deny") => void;
  busy: number | null;
}) {
  if (!approvals.length) {
    return (
      <div className="empty" style={{ padding: "34px 10px" }}>
        Nothing is waiting on you. When an agent asks to spend money, it lands here.
      </div>
    );
  }

  return (
    <>
      {approvals.map((a) => {
        const payload = a.payload ?? {};
        const who = agentStyle(a.requested_by?.toLowerCase());
        return (
          <div key={a.id} className={`approval ${a.status}`}>
            <div className="ap-top">
              <span className="ap-kind">{a.kind.replace("_", " ")}</span>
              {a.ticket_id && <span className="ap-kind">· ticket {a.ticket_id}</span>}
              <span className="ap-amount" style={{ color: a.status === "pending" ? "#ff6fa5" : undefined }}>
                {money(a.amount)}
              </span>
            </div>

            <div className="ap-memo">{a.memo}</div>

            {a.kind === "purchase_order" && payload.sku ? (
              <div className="ap-by">
                {String(payload.qty)} × {String(payload.sku)} ({String(payload.size)}) from{" "}
                {String(payload.vendor)} · arrives {String(payload.expected_date)}
              </div>
            ) : null}

            <div className="ap-by" style={{ color: who.colour }}>
              requested by {a.requested_by}
            </div>

            {a.status === "pending" ? (
              <div className="ap-actions">
                <button
                  className="ap-btn yes"
                  disabled={busy !== null}
                  onClick={() => onDecide(a.id, "approve")}
                >
                  {busy === a.id ? "Paying…" : "Approve"}
                </button>
                <button
                  className="ap-btn no"
                  disabled={busy !== null}
                  onClick={() => onDecide(a.id, "deny")}
                >
                  Deny
                </button>
              </div>
            ) : (
              <div className="ap-done">
                {a.status === "approved" ? "✓ Approved" : a.status === "denied" ? "✕ Denied" : "⚠ Failed"}
                {a.decided_by ? ` by ${a.decided_by}` : ""}
              </div>
            )}
          </div>
        );
      })}
    </>
  );
}

/** Per-agent recap of what each one actually did on this ticket. */
export function AgentSummary({ events, run }: { events: AuditEvent[]; run: RunState | null }) {
  const byAgent = new Map<string, { tools: string[]; said: string[] }>();

  for (const e of events) {
    if (!e.agent || e.agent === "supervisor") continue;
    if (!byAgent.has(e.agent)) byAgent.set(e.agent, { tools: [], said: [] });
    const entry = byAgent.get(e.agent)!;
    if (e.kind === "tool_call" && e.tool) entry.tools.push(e.tool);
    if ((e.kind === "agent_finished" || e.kind === "ticket_finished") && e.summary) {
      entry.said.push(e.summary);
    }
  }

  const decision = run?.summary?.tickets?.[0]?.decision;
  const usage = run?.summary?.usage;

  if (!byAgent.size) {
    return (
      <div className="empty" style={{ padding: "34px 10px" }}>
        Once a run finishes, a recap of what every agent did appears here.
      </div>
    );
  }

  return (
    <>
      {decision && (
        <div className="verdict">
          <h4>Boss's decision · ticket {run?.ticket_id}</h4>
          <p>{decision.decision}</p>
          <p className="why">{decision.reasoning}</p>
          {decision.awaiting_approval?.length > 0 && (
            <p className="why">
              Waiting on approval {decision.awaiting_approval.join(", ")}.
            </p>
          )}
          {usage && (
            <div className="verdict-usage">
              {usage.requests} model calls · {usage.tool_calls} tool calls ·{" "}
              {usage.total_tokens.toLocaleString()} tokens
            </div>
          )}
        </div>
      )}

      {[...byAgent.entries()].map(([name, info]) => {
        const who = agentStyle(name);
        const unique = [...new Set(info.tools)];
        return (
          <div className="summary-card" key={name}>
            <div className="summary-head">
              <div className="avatar sm" style={{ background: who.colour }}>
                {who.initials}
              </div>
              <span className="summary-name" style={{ color: who.colour }}>
                {who.label}
              </span>
              <span className="summary-count">{info.tools.length} calls</span>
            </div>

            {info.said.length > 0 && (
              <div style={{ fontSize: "12.5px", color: "var(--dim)", marginBottom: 8 }}>
                {info.said[info.said.length - 1]}
              </div>
            )}

            {unique.length > 0 && (
              <ul className="summary-list">
                {unique.map((t) => (
                  <li key={t}>
                    <code>{t}</code>
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </>
  );
}

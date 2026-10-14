import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { AGENTS, ORDER } from "./agents";
import { ActivityFeed } from "./components/ActivityFeed";
import { TicketList } from "./components/TicketList";
import { AgentSummary, ApprovalQueue, CashCard } from "./components/SidePanel";
import type { Approval, AuditEvent, Cash, Health, RunState, Ticket } from "./types";

const SUPERVISOR = "Yunsik Jung";

export default function App() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [cash, setCash] = useState<Cash | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [health, setHealth] = useState<Health | null>(null);

  const [selected, setSelected] = useState<number | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [run, setRun] = useState<RunState | null>(null);
  const [busyApproval, setBusyApproval] = useState<number | null>(null);
  const [toast, setToast] = useState<{ text: string; bad?: boolean } | null>(null);

  const cursor = useRef(0);
  const running = run?.status === "running";

  const flash = (text: string, bad = false) => {
    setToast({ text, bad });
    setTimeout(() => setToast(null), 4200);
  };

  const refreshBoard = useCallback(async () => {
    try {
      const [t, c, a, h] = await Promise.all([
        api.tickets(),
        api.cash(),
        api.approvals(),
        api.health(),
      ]);
      setTickets(t.tickets);
      setCash(c);
      setApprovals(a.approvals);
      setHealth(h);
      if (selected === null && t.tickets.length) setSelected(t.tickets[0].id);
    } catch {
      setHealth(null);
    }
  }, [selected]);

  // The audit trail is append-only across the whole project, so on load show
  // only the most recent run rather than replaying every run ever recorded.
  const initFeed = useCallback(async () => {
    try {
      const all = await api.activity(0);
      cursor.current = all.total;
      const lastRun = all.events.length ? all.events[all.events.length - 1].run_id : null;
      setEvents(lastRun ? all.events.filter((e) => e.run_id === lastRun) : []);
    } catch {
      /* ignore -- the poller retries */
    }
  }, []);

  useEffect(() => {
    refreshBoard();
    initFeed();
  }, []);

  // Poll the activity feed hard while a run is live, gently when idle.
  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const data = await api.activity(cursor.current);
        if (stop) return;
        if (data.events.length) {
          cursor.current += data.events.length;
          setEvents((prev) => [...prev, ...data.events]);
        }
        if (!running) await refreshBoard();
        if (run && run.status === "running") {
          const latest = await api.run(run.run_id);
          if (stop) return;
          if (latest.status !== "running") {
            setRun(latest);
            await refreshBoard();
            flash(
              latest.status === "failed"
                ? `Run failed: ${latest.error ?? "unknown error"}`
                : `Ticket ${latest.ticket_id} finished.`,
              latest.status === "failed",
            );
          }
        }
      } catch {
        /* backend may be restarting; the next tick retries */
      }
    };
    const id = setInterval(tick, running ? 1200 : 4000);
    tick();
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [running, run?.run_id, refreshBoard]);

  const startRun = async (ticketId: number) => {
    setEvents([]);
    cursor.current = (await api.activity(0)).total;
    try {
      const state = await api.runTicket(ticketId);
      setRun(state);
      flash(`Ticket ${ticketId} handed to the team.`);
      await refreshBoard();
    } catch (err) {
      flash(String(err), true);
    }
  };

  const decide = async (id: number, decision: "approve" | "deny") => {
    setBusyApproval(id);
    try {
      const result = await api.decide(id, decision, SUPERVISOR);
      flash(result.message);
      await refreshBoard();
    } catch (err) {
      flash(String(err), true);
    } finally {
      setBusyApproval(null);
    }
  };

  const resetAll = async () => {
    try {
      await api.reset();
      setEvents([]);
      setRun(null);
      cursor.current = (await api.activity(0)).total;
      await refreshBoard();
      flash("Shop reset to its opening state.");
    } catch (err) {
      flash(String(err), true);
    }
  };

  const pending = approvals.filter((a) => a.status === "pending");
  const activeAgents = new Set(events.slice(-6).map((e) => e.agent));
  const resolved = tickets.filter((t) => !t.is_open).length;
  const money = (n: number) => n.toLocaleString("en-US", { style: "currency", currency: "USD" });

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">CC</div>
          <div>
            <div className="brand-name">Campus Customs</div>
            <div className="brand-sub">Multi-agent operations desk</div>
          </div>
        </div>

        <div className="topbar-spacer" />

        <div className="stat">
          <span className="stat-label">Shop date</span>
          <span className="stat-value">2026-08-31</span>
        </div>
        <div className="stat">
          <span className="stat-label">Tickets closed</span>
          <span className="stat-value">
            {resolved} / {tickets.length}
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">Checking</span>
          <span className="stat-value">{cash ? money(cash.balance) : "—"}</span>
        </div>
        <div className="stat">
          <span className="stat-label">Backend</span>
          <span className="stat-value" style={{ fontSize: 13 }}>
            <span className={`dot ${health?.mcp_reachable ? "up" : "down"}`} />
            {health?.mcp_reachable ? health.model : "offline"}
          </span>
        </div>

        <button className="ghost-btn" onClick={resetAll} disabled={running}>
          Reset shop
        </button>
      </header>

      <div className="workspace">
        {/* ------------------------------------------------ tickets */}
        <div className="col">
          <div className="col-head">
            <span>The board</span>
            <span className="count-pill">{tickets.length} tickets</span>
          </div>
          <div className="col-body">
            <TicketList
              tickets={tickets}
              selected={selected}
              onSelect={setSelected}
              onRun={startRun}
              busyTicket={running ? (run?.ticket_id ?? null) : null}
              runActive={running}
            />
          </div>
        </div>

        {/* ------------------------------------------------ feed */}
        <div className="col">
          <div className="feed-head">
            <div>
              <div className="feed-title">Agent floor</div>
              <div className="feed-sub">
                {running
                  ? `Working ticket ${run?.ticket_id}…`
                  : events.length
                    ? `${events.length} events`
                    : "Idle"}
              </div>
            </div>
            <div className="roster">
              {ORDER.map((key) => {
                const a = AGENTS[key];
                const live = running && activeAgents.has(key);
                return (
                  <div
                    key={key}
                    className={`roster-chip ${live ? "live" : ""}`}
                    style={{ color: live ? a.colour : undefined }}
                    title={a.role}
                  >
                    <div className="avatar sm" style={{ background: a.colour }}>
                      {a.initials}
                    </div>
                    {a.label}
                  </div>
                );
              })}
            </div>
          </div>
          <div className="feed">
            <ActivityFeed events={events} running={running} />
          </div>
        </div>

        {/* ------------------------------------------------ money + recap */}
        <div className="col">
          <div className="col-head">
            <span>Your desk</span>
            {pending.length > 0 && (
              <span className="count-pill" style={{ color: "#ff6fa5", borderColor: "#5c1130" }}>
                {pending.length} awaiting you
              </span>
            )}
          </div>
          <div className="col-body">
            <CashCard cash={cash} />
            <ApprovalQueue approvals={approvals} onDecide={decide} busy={busyApproval} />
            <div className="col-head" style={{ padding: "18px 0 10px", borderBottom: "none" }}>
              What the team did
            </div>
            <AgentSummary events={events} run={run} />
          </div>
        </div>
      </div>

      {toast && <div className={`toast ${toast.bad ? "bad" : ""}`}>{toast.text}</div>}
    </div>
  );
}

import { useEffect, useRef } from "react";
import type { AuditEvent } from "../types";
import { agentStyle } from "../agents";

interface Props {
  events: AuditEvent[];
  running: boolean;
}

/** Event kinds that carry no operator value on their own. */
const HIDDEN = new Set(["tool_result", "run_started", "run_finished", "agent_started"]);

const time = (ts: string) => {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return "";
  }
};

const compactArgs = (args?: Record<string, unknown>) => {
  if (!args) return "";
  const parts = Object.entries(args)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`);
  const text = parts.join(" ");
  return text.length > 72 ? `${text.slice(0, 72)}…` : text;
};

export function ActivityFeed({ events, running }: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [events.length]);

  const visible = events.filter((e) => !HIDDEN.has(e.kind));

  if (!visible.length) {
    return (
      <div className="empty">
        <h4>The desk is quiet</h4>
        Pick a ticket on the left and hand it to the team. Everything the agents
        say and every tool they touch shows up here, live.
      </div>
    );
  }

  return (
    <>
      {visible.map((e, i) => {
        const who = agentStyle(e.agent);
        const last = i === visible.length - 1;
        return (
          <div className="ev" key={`${e.run_id}-${e.seq}-${i}`}>
            <div className="ev-rail">
              <div className="avatar sm" style={{ background: who.colour }}>
                {who.initials}
              </div>
            </div>

            <div className="ev-body">
              <div>
                <span className="ev-name" style={{ color: who.colour }}>
                  {who.label}
                </span>
                <span className="ev-time">{time(e.ts)}</span>
                {e.depth > 0 && <span className="ev-depth">depth {e.depth}</span>}
                {running && last && (
                  <span className="typing">
                    <i /> <i /> <i />
                  </span>
                )}
              </div>

              {e.kind === "tool_call" && (
                <div className="tool-line">
                  <b>{e.tool}</b>
                  <span className="tool-args">{compactArgs(e.tool_args)}</span>
                </div>
              )}

              {e.kind === "delegation" && (
                <>
                  <div className="handoff">
                    → asks{" "}
                    <b style={{ color: agentStyle(String(e.detail?.target)).colour }}>
                      {agentStyle(String(e.detail?.target)).label}
                    </b>
                  </div>
                  <div className="ev-text quiet">{String(e.detail?.task ?? "")}</div>
                </>
              )}

              {e.kind === "delegation_refused" && (
                <div className="ev-flag bad">Delegation refused — {e.summary}</div>
              )}

              {e.kind === "agent_finished" && <div className="ev-text">{e.summary}</div>}

              {e.kind === "ticket_started" && (
                <div className="ev-text quiet">Picked up {e.summary}</div>
              )}

              {e.kind === "approval_requested" && (
                <div className="ev-flag">
                  ⏸ Waiting on you — {e.summary}
                </div>
              )}

              {e.kind === "approval_resolved" && (
                <div className="ev-flag good">{e.summary}</div>
              )}

              {e.kind === "ticket_finished" && (
                <div className="ev-flag good">Decision — {e.summary}</div>
              )}

              {e.kind === "error" && <div className="ev-flag bad">{e.summary}</div>}
            </div>
          </div>
        );
      })}
      <div ref={endRef} />
    </>
  );
}

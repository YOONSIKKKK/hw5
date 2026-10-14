import type { Ticket } from "../types";
import { agentStyle } from "../agents";

interface Props {
  tickets: Ticket[];
  selected: number | null;
  onSelect: (id: number) => void;
  onRun: (id: number) => void;
  busyTicket: number | null;
  runActive: boolean;
}

const TYPE_LABEL: Record<string, string> = {
  customer_order: "Customer order",
  rent_notice: "Rent notice",
  price_override: "Discount request",
};

export function TicketList({ tickets, selected, onSelect, onRun, busyTicket, runActive }: Props) {
  return (
    <>
      {tickets.map((t) => {
        const isSel = t.id === selected;
        const owner = t.assigned_to ? agentStyle(t.assigned_to) : null;
        return (
          <div
            key={t.id}
            className={`ticket ${isSel ? "sel" : ""} ${t.status === "resolved" ? "done" : ""}`}
            onClick={() => onSelect(t.id)}
          >
            <div className="ticket-top">
              <span className="ticket-id">#{t.id}</span>
              <span className="ticket-id">· {TYPE_LABEL[t.type] ?? t.type}</span>
              <span className={`badge ${t.status}`}>{t.status.replace("_", " ")}</span>
            </div>

            <div className="ticket-subject">{t.subject}</div>
            <div className="ticket-req">{t.requester}</div>

            {t.sku && (
              <div className="ticket-meta">
                {t.qty} × {t.sku} {t.size && `· size ${t.size}`}
              </div>
            )}
            {t.lease_id && <div className="ticket-meta">lease {t.lease_id}</div>}

            {owner && (
              <div className="ticket-meta" style={{ color: owner.colour }}>
                handled by {owner.label}
              </div>
            )}

            {t.resolution && <div className="ticket-res">{t.resolution}</div>}

            {isSel && (
              <button
                className={`run-btn ${busyTicket === t.id ? "busy" : ""}`}
                disabled={runActive}
                onClick={(e) => {
                  e.stopPropagation();
                  onRun(t.id);
                }}
              >
                {busyTicket === t.id
                  ? "Agents working…"
                  : runActive
                    ? "Another run in progress"
                    : t.status === "resolved"
                      ? "Run agents again"
                      : "Hand to the agent team"}
              </button>
            )}
          </div>
        );
      })}
    </>
  );
}

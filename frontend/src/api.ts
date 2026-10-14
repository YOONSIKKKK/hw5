import type { Approval, AuditEvent, Cash, Draft, Health, RunState, Ticket } from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.text()) || `${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  health: () => get<Health>("/api/health"),

  tickets: () =>
    get<{ tickets: Ticket[]; open_count: number; resolved_count: number }>("/api/tickets"),

  cash: () => get<Cash>("/api/cash"),

  approvals: () => get<{ approvals: Approval[]; pending: number }>("/api/approvals"),

  drafts: () => get<{ drafts: Draft[] }>("/api/drafts"),

  activity: (after: number) =>
    get<{ events: AuditEvent[]; cursor: number; total: number; run_active: string | null }>(
      `/api/activity?after=${after}&limit=500`,
    ),

  runTicket: (ticketId: number) =>
    post<RunState>(`/api/tickets/${ticketId}/run`, { wait: false }),

  run: (runId: string) => get<RunState>(`/api/runs/${runId}`),

  decide: (approvalId: number, decision: "approve" | "deny", approver: string, note?: string) =>
    post<{ message: string; cash_before: number; cash_after: number }>(
      `/api/approvals/${approvalId}/decision`,
      { decision, approver, note },
    ),

  reset: () => post<{ ok: boolean; cash: number }>("/api/reset"),
};

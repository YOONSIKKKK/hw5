export type TicketStatus = "open" | "in_progress" | "blocked" | "resolved";

export interface Ticket {
  id: number;
  type: string;
  requester: string;
  subject: string;
  sku: string | null;
  size: string | null;
  qty: number | null;
  lease_id: number | null;
  invoice_id: number | null;
  status: TicketStatus;
  notes: string | null;
  created_at: string;
  assigned_to: string | null;
  resolution: string | null;
  is_open: boolean;
}

export interface AuditEvent {
  run_id: string;
  seq: number;
  ts: string;
  kind: string;
  agent?: string;
  ticket_id?: number;
  depth: number;
  summary?: string;
  tool?: string;
  tool_args?: Record<string, unknown>;
  tool_result?: unknown;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  detail?: Record<string, unknown>;
}

export interface Approval {
  id: number;
  kind: string;
  ref_id: number | null;
  ticket_id: number | null;
  amount: number;
  account: string;
  memo: string | null;
  payload: Record<string, unknown>;
  status: "pending" | "approved" | "denied" | "failed";
  requested_by: string;
  requested_at: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  result: Record<string, unknown> | null;
}

export interface Cash {
  balance: number;
  pending_approval_total: number;
  uncommitted: number;
}

export interface RunState {
  run_id: string;
  ticket_id: number;
  status: "running" | "finished" | "failed";
  started_at: string;
  finished_at?: string;
  error?: string;
  summary?: {
    usage: {
      requests: number;
      tool_calls: number;
      total_tokens: number;
    };
    tickets: Array<{
      ticket_id: number;
      decision?: {
        status: TicketStatus;
        decision: string;
        reasoning: string;
        agents_consulted: string[];
        awaiting_approval: number[];
      };
      error?: string;
    }>;
  };
}

export interface Health {
  ok: boolean;
  model: string;
  mcp_reachable: boolean;
  run_active: string | null;
}

export interface Draft {
  id: number;
  ticket_id: number | null;
  channel: string;
  recipient: string;
  subject: string;
  body: string;
  author: string;
  status: string;
}

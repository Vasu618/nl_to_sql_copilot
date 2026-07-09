// API client for the FastAPI backend. Uses /api/* prefix which Next.js
// rewrites to http://127.0.0.1:8000/* in dev (see next.config.ts).

import type {
  AskResponse,
  ChartType,
  ConversationTurn,
  FinalStatus,
  SchemaResponse,
} from "@/types/api";

const API_BASE = "/api";

export async function fetchSchema(): Promise<SchemaResponse> {
  const res = await fetch(`${API_BASE}/schema`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Failed to fetch schema: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function askQuestion(question: string): Promise<AskResponse> {
  const res = await fetch(`${API_BASE}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) {
    throw new Error(`/ask returned ${res.status}: ${await res.text()}`);
  }
  return res.json();
}

// Re-run an edited SQL string directly. The backend /ask endpoint always
// generates fresh SQL via the LLM, so for the "edit SQL and re-run" feature
// we add a separate /execute endpoint that bypasses LLM generation but
// still goes through the validator + read-only execution path.
// (This endpoint is added to the backend in Week 3b — see backend/app/routes/ask.py.)
export async function executeSql(sql: string): Promise<AskResponse> {
  const res = await fetch(`${API_BASE}/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sql }),
  });
  if (!res.ok) {
    throw new Error(`/execute returned ${res.status}: ${await res.text()}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Status badge styling helpers
// ---------------------------------------------------------------------------

export function statusLabel(status: FinalStatus): string {
  switch (status) {
    case "success":
      return "Answered";
    case "no_answer":
      return "No confident answer";
    case "validation_failed":
      return "Validation failed";
    case "execution_failed":
      return "Execution failed";
    case "llm_failed":
      return "LLM error";
    default:
      return status;
  }
}

export function statusColor(status: FinalStatus): {
  bg: string;
  text: string;
  border: string;
} {
  switch (status) {
    case "success":
      return { bg: "var(--success-soft)", text: "var(--success)", border: "var(--success)" };
    case "no_answer":
      return { bg: "var(--warning-soft)", text: "var(--warning)", border: "var(--warning)" };
    case "validation_failed":
    case "execution_failed":
    case "llm_failed":
      return { bg: "var(--danger-soft)", text: "var(--danger)", border: "var(--danger)" };
    default:
      return { bg: "var(--bg-elevated)", text: "var(--text-muted)", border: "var(--border-strong)" };
  }
}

export function chartTypeLabel(t: ChartType | null): string {
  switch (t) {
    case "bar":
      return "Bar chart (categorical comparison)";
    case "line":
      return "Line chart (time series)";
    case "pie":
      return "Pie chart (part-of-whole)";
    case "table":
      return "Table (no chart)";
    case "none":
      return "No chart (single value or empty)";
    default:
      return "—";
  }
}

// Generate a stable ID for conversation turns (no crypto dependency).
export function newTurnId(): string {
  return `turn-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function emptyTurn(question: string): ConversationTurn {
  return {
    id: newTurnId(),
    question,
    response: null,
    isLoading: true,
    error: null,
    timestamp: Date.now(),
  };
}

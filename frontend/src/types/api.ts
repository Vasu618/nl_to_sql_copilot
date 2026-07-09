// Type definitions matching the FastAPI backend's response shapes.
// Kept in sync with backend/app/routes/ask.py and schema_context.py.

export type ChartType = "bar" | "line" | "pie" | "table" | "none";
export type FinalStatus =
  | "success"
  | "no_answer"
  | "validation_failed"
  | "execution_failed"
  | "llm_failed";

export interface SchemaColumn {
  name: string;
  type: string;
  nullable: boolean;
  primary_key: boolean;
  foreign_key: string | null;
}

export interface SchemaTable {
  name: string;
  columns: SchemaColumn[];
  sample_rows: Record<string, unknown>[];
}

export interface SchemaResponse {
  tables: SchemaTable[];
}

export interface AttemptInfo {
  attempt_number: number;
  sql: string;
  rationale: string;
  validation_ok: boolean;
  validation_error: string | null;
  execution_ok: boolean;
  execution_error: string | null;
  row_count: number;
  execution_ms: number;
}

export interface AskResponse {
  question: string;
  question_id: string | null;
  final_status: FinalStatus;
  correction_attempts: number;
  final_sql: string | null;
  rationale: string | null;
  rows: Record<string, unknown>[] | null;
  row_count: number | null;
  truncated: boolean;
  execution_ms: number;
  plain_english_answer: string | null;
  suggested_chart_type: ChartType | null;
  error: string | null;
  attempts: AttemptInfo[];
  pipeline: string[];
  // Present when called via /execute (edited SQL re-run). /ask leaves these null.
  validation?: {
    ok: boolean;
    limit_injected: boolean;
    limit_shrunk: boolean;
    rejected_table: string | null;
    rejected_column: string | null;
    error: string | null;
  } | null;
  execution?: {
    ok: boolean;
    row_count: number;
    truncated: boolean;
    execution_ms: number;
    error: string | null;
  } | null;
}

export interface ConversationTurn {
  id: string;
  question: string;
  response: AskResponse | null;
  isLoading: boolean;
  error: string | null;
  timestamp: number;
}

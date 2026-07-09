"use client";

import { useState } from "react";
import type { AskResponse } from "@/types/api";
import { statusColor, statusLabel } from "@/lib/api";
import { CheckCircle2, AlertCircle, AlertTriangle, Code2, ChevronDown, ChevronRight, Play, Loader2 } from "lucide-react";
import { executeSql } from "@/lib/api";

interface SqlPanelProps {
  response: AskResponse;
  onRerun: (newResponse: AskResponse) => void;
}

export function SqlPanel({ response, onRerun }: SqlPanelProps) {
  const [isOpen, setIsOpen] = useState(true);
  const [isEditing, setIsEditing] = useState(false);
  const [editedSql, setEditedSql] = useState(response.final_sql || "");
  const [isRerunning, setIsRerunning] = useState(false);
  const [rerunError, setRerunError] = useState<string | null>(null);

  const status = response.final_status;
  const colors = statusColor(status);
  const StatusIcon =
    status === "success"
      ? CheckCircle2
      : status === "no_answer"
      ? AlertTriangle
      : AlertCircle;

  const startEdit = () => {
    setEditedSql(response.final_sql || "");
    setIsEditing(true);
  };

  const rerun = async () => {
    setIsRerunning(true);
    setRerunError(null);
    try {
      const newResp = await executeSql(editedSql);
      onRerun(newResp);
      setIsEditing(false);
    } catch (e) {
      setRerunError(String(e));
    } finally {
      setIsRerunning(false);
    }
  };

  return (
    <div
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border)",
        borderRadius: 8,
        marginBottom: 12,
        overflow: "hidden",
      }}
    >
      {/* Header bar: status + collapse toggle */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        style={{
          width: "100%",
          padding: "10px 14px",
          background: "var(--bg-elevated)",
          border: "none",
          borderBottom: isOpen ? "1px solid var(--border)" : "none",
          display: "flex",
          alignItems: "center",
          gap: 10,
          textAlign: "left",
        }}
      >
        {isOpen ? (
          <ChevronDown size={14} style={{ color: "var(--text-subtle)" }} />
        ) : (
          <ChevronRight size={14} style={{ color: "var(--text-subtle)" }} />
        )}
        <StatusIcon size={14} style={{ color: colors.text }} />
        <span style={{ fontWeight: 600, fontSize: 13, flex: 1 }}>
          {statusLabel(status)}
        </span>
        {response.correction_attempts > 0 && (
          <span
            style={{
              fontSize: 11,
              padding: "2px 8px",
              background: "var(--warning-soft)",
              color: "var(--warning)",
              borderRadius: 10,
            }}
          >
            self-corrected ×{response.correction_attempts}
          </span>
        )}
        {response.execution_ms > 0 && (
          <span style={{ fontSize: 11, color: "var(--text-subtle)" }}>
            {response.execution_ms}ms
          </span>
        )}
        <span
          style={{
            fontSize: 11,
            padding: "2px 8px",
            background: colors.bg,
            color: colors.text,
            borderRadius: 10,
            fontWeight: 600,
            border: `1px solid ${colors.border}`,
          }}
        >
          {statusLabel(status)}
        </span>
      </button>

      {isOpen && (
        <div style={{ padding: "12px 14px" }}>
          {/* Rationale */}
          {response.rationale && (
            <div
              style={{
                marginBottom: 10,
                padding: "8px 10px",
                background: "var(--bg-elevated)",
                borderRadius: 6,
                fontSize: 12,
                color: "var(--text-muted)",
                fontStyle: "italic",
              }}
            >
              {response.rationale}
            </div>
          )}

          {/* SQL display / editor */}
          <div style={{ position: "relative" }}>
            <div
              style={{
                position: "absolute",
                top: 8,
                left: 10,
                color: "var(--text-subtle)",
                fontSize: 10,
                fontWeight: 600,
                letterSpacing: 0.5,
                textTransform: "uppercase",
                display: "flex",
                alignItems: "center",
                gap: 4,
                zIndex: 1,
              }}
            >
              <Code2 size={10} /> SQL
            </div>
            {isEditing ? (
              <textarea
                value={editedSql}
                onChange={(e) => setEditedSql(e.target.value)}
                style={{
                  width: "100%",
                  minHeight: 160,
                  padding: "28px 14px 14px",
                  background: "var(--code-bg)",
                  color: "var(--code-text)",
                  border: "1px solid var(--border-strong)",
                  borderRadius: 6,
                  fontFamily: "monospace",
                  fontSize: 12,
                  lineHeight: 1.5,
                  resize: "vertical",
                  outline: "none",
                }}
                spellCheck={false}
              />
            ) : (
              <pre
                style={{
                  margin: 0,
                  padding: "28px 14px 14px",
                  background: "var(--code-bg)",
                  color: "var(--code-text)",
                  borderRadius: 6,
                  fontFamily: "monospace",
                  fontSize: 12,
                  lineHeight: 1.5,
                  overflowX: "auto",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                }}
              >
                {response.final_sql || "(no SQL generated)"}
              </pre>
            )}
          </div>

          {/* Action buttons */}
          <div
            style={{
              marginTop: 8,
              display: "flex",
              gap: 8,
              alignItems: "center",
              flexWrap: "wrap",
            }}
          >
            {!isEditing ? (
              <button
                onClick={startEdit}
                disabled={!response.final_sql}
                style={{
                  padding: "5px 12px",
                  fontSize: 12,
                  background: "var(--bg-elevated)",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  color: "var(--text)",
                }}
              >
                Edit SQL
              </button>
            ) : (
              <>
                <button
                  onClick={rerun}
                  disabled={isRerunning}
                  style={{
                    padding: "5px 12px",
                    fontSize: 12,
                    background: "var(--accent)",
                    color: "white",
                    border: "none",
                    borderRadius: 6,
                    display: "flex",
                    alignItems: "center",
                    gap: 5,
                  }}
                >
                  {isRerunning ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <Play size={12} />
                  )}
                  Re-run validated
                </button>
                <button
                  onClick={() => setIsEditing(false)}
                  disabled={isRerunning}
                  style={{
                    padding: "5px 12px",
                    fontSize: 12,
                    background: "transparent",
                    border: "1px solid var(--border)",
                    borderRadius: 6,
                    color: "var(--text-muted)",
                  }}
                >
                  Cancel
                </button>
                <span style={{ fontSize: 11, color: "var(--text-subtle)" }}>
                  Re-runs through the same validator + read-only execution path.
                </span>
              </>
            )}
            {rerunError && (
              <span style={{ fontSize: 11, color: "var(--danger)" }}>
                {rerunError}
              </span>
            )}
          </div>

          {/* Error message if status is failure */}
          {response.error && status !== "success" && status !== "no_answer" && (
            <div
              style={{
                marginTop: 10,
                padding: "8px 10px",
                background: "var(--danger-soft)",
                border: `1px solid var(--danger)`,
                borderRadius: 6,
                fontSize: 12,
                color: "var(--danger)",
              }}
            >
              <strong>Error:</strong> {response.error}
            </div>
          )}

          {/* Correction attempts trace (only if any) */}
          {response.attempts.length > 1 && (
            <details style={{ marginTop: 10 }}>
              <summary
                style={{
                  cursor: "pointer",
                  fontSize: 11,
                  color: "var(--text-subtle)",
                }}
              >
                {response.attempts.length} attempts (self-correction trace)
              </summary>
              <ol style={{ marginTop: 8, paddingLeft: 20, fontSize: 11 }}>
                {response.attempts.map((a) => (
                  <li key={a.attempt_number} style={{ marginBottom: 6 }}>
                    <strong>Attempt {a.attempt_number}:</strong>{" "}
                    {!a.validation_ok ? (
                      <span style={{ color: "var(--danger)" }}>
                        validation failed — {a.validation_error}
                      </span>
                    ) : !a.execution_ok ? (
                      <span style={{ color: "var(--danger)" }}>
                        execution failed — {a.execution_error}
                      </span>
                    ) : (
                      <span style={{ color: "var(--success)" }}>
                        succeeded, {a.row_count} rows in {a.execution_ms}ms
                      </span>
                    )}
                  </li>
                ))}
              </ol>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

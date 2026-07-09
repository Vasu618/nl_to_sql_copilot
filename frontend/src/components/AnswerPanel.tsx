"use client";

import type { AskResponse } from "@/types/api";
import { statusColor, statusLabel } from "@/lib/api";
import { CheckCircle2, AlertTriangle, AlertCircle, MessageSquare } from "lucide-react";

interface AnswerPanelProps {
  response: AskResponse;
}

export function AnswerPanel({ response }: AnswerPanelProps) {
  const status = response.final_status;
  const colors = statusColor(status);
  const Icon =
    status === "success"
      ? CheckCircle2
      : status === "no_answer"
      ? AlertTriangle
      : AlertCircle;

  const answer = response.plain_english_answer;

  return (
    <div
      style={{
        background: "var(--bg-panel)",
        border: `1px solid ${colors.border}`,
        borderLeft: `4px solid ${colors.border}`,
        borderRadius: 8,
        padding: "14px 16px",
        marginBottom: 12,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 8,
        }}
      >
        <Icon size={16} style={{ color: colors.text }} />
        <strong style={{ fontSize: 13, color: colors.text }}>
          {statusLabel(status)}
        </strong>
        <span
          style={{
            marginLeft: "auto",
            fontSize: 11,
            color: "var(--text-subtle)",
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}
        >
          <MessageSquare size={11} /> Plain-English answer
        </span>
      </div>

      {answer ? (
        <p
          style={{
            margin: 0,
            fontSize: 14,
            lineHeight: 1.6,
            color: "var(--text)",
          }}
        >
          {answer}
        </p>
      ) : (
        <p
          style={{
            margin: 0,
            fontSize: 13,
            color: "var(--text-muted)",
            fontStyle: "italic",
          }}
        >
          (No explanation generated.)
        </p>
      )}

      {response.suggested_chart_type && response.suggested_chart_type !== "none" && (
        <div
          style={{
            marginTop: 10,
            paddingTop: 10,
            borderTop: "1px solid var(--border)",
            fontSize: 11,
            color: "var(--text-subtle)",
          }}
        >
          Suggested visualization:{" "}
          <strong style={{ color: "var(--text-muted)" }}>
            {response.suggested_chart_type}
          </strong>
        </div>
      )}
    </div>
  );
}

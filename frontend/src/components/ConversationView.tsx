"use client";

import type { ConversationTurn } from "@/types/api";
import { SqlPanel } from "./SqlPanel";
import { AnswerPanel } from "./AnswerPanel";
import { ChartPanel } from "./ChartPanel";
import { ResultsTable } from "./ResultsTable";
import { Loader2, User, Sparkles } from "lucide-react";

interface ConversationViewProps {
  turns: ConversationTurn[];
  onUpdateTurn: (id: string, updater: (t: ConversationTurn) => ConversationTurn) => void;
}

export function ConversationView({ turns, onUpdateTurn }: ConversationViewProps) {
  if (turns.length === 0) {
    return (
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--text-muted)",
          padding: 32,
          textAlign: "center",
        }}
      >
        <Sparkles size={32} style={{ color: "var(--accent)", marginBottom: 12 }} />
        <h2 style={{ fontSize: 18, fontWeight: 600, color: "var(--text)", margin: "0 0 4px" }}>
          Ask a question to get started
        </h2>
        <p style={{ fontSize: 13, maxWidth: 400 }}>
          Plain-English questions about the e-commerce database. The system
          generates validated SQL, executes it against a read-only role, and
          explains the result — with a self-correction loop and anti-overclaiming
          safety checks.
        </p>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
      {turns.map((turn) => (
        <div key={turn.id} style={{ marginBottom: 28 }}>
          {/* User question bubble */}
          <div
            style={{
              display: "flex",
              gap: 10,
              marginBottom: 12,
            }}
          >
            <div
              style={{
                width: 28,
                height: 28,
                borderRadius: "50%",
                background: "var(--bg-elevated)",
                color: "var(--text-muted)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <User size={14} />
            </div>
            <div
              style={{
                background: "var(--bg-elevated)",
                padding: "10px 14px",
                borderRadius: 12,
                borderTopLeftRadius: 2,
                fontSize: 14,
                color: "var(--text)",
                maxWidth: "80%",
              }}
            >
              {turn.question}
            </div>
          </div>

          {/* Response area */}
          <div style={{ paddingLeft: 38 }}>
            {turn.isLoading && (
              <div
                style={{
                  padding: "16px",
                  background: "var(--bg-panel)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  color: "var(--text-muted)",
                  fontSize: 13,
                }}
              >
                <Loader2 size={16} className="animate-spin" style={{ color: "var(--accent)" }} />
                Generating SQL via LLM, validating, executing, explaining…
              </div>
            )}

            {turn.error && !turn.isLoading && (
              <div
                style={{
                  padding: "12px 14px",
                  background: "var(--danger-soft)",
                  border: "1px solid var(--danger)",
                  borderRadius: 8,
                  color: "var(--danger)",
                  fontSize: 13,
                }}
              >
                <strong>Request failed:</strong> {turn.error}
              </div>
            )}

            {turn.response && !turn.isLoading && (
              <>
                <SqlPanel
                  response={turn.response}
                  onRerun={(newResp) =>
                    onUpdateTurn(turn.id, (t) => ({ ...t, response: newResp }))
                  }
                />
                <AnswerPanel response={turn.response} />
                <ChartPanel response={turn.response} />
                <ResultsTable response={turn.response} />
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

"use client";

import { useCallback, useState } from "react";
import type { AskResponse, ConversationTurn } from "@/types/api";
import { askQuestion, emptyTurn } from "@/lib/api";
import { SchemaSidebar } from "@/components/SchemaSidebar";
import { QuestionInput } from "@/components/QuestionInput";
import { ConversationView } from "@/components/ConversationView";

export default function HomePage() {
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [isAsking, setIsAsking] = useState(false);

  const updateTurn = useCallback(
    (id: string, updater: (t: ConversationTurn) => ConversationTurn) => {
      setTurns((prev) => prev.map((t) => (t.id === id ? updater(t) : t)));
    },
    [],
  );

  const submit = useCallback(async (question: string) => {
    const turn = emptyTurn(question);
    setTurns((prev) => [...prev, turn]);
    setIsAsking(true);
    try {
      const response: AskResponse = await askQuestion(question);
      updateTurn(turn.id, (t) => ({
        ...t,
        response,
        isLoading: false,
      }));
    } catch (e) {
      updateTurn(turn.id, (t) => ({
        ...t,
        isLoading: false,
        error: String(e),
      }));
    } finally {
      setIsAsking(false);
    }
  }, [updateTurn]);

  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <SchemaSidebar />
      <main
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          minWidth: 0,
        }}
      >
        <header
          style={{
            padding: "12px 24px",
            borderBottom: "1px solid var(--border)",
            background: "var(--bg-panel)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div>
            <h1
              style={{
                margin: 0,
                fontSize: 16,
                fontWeight: 600,
              }}
            >
              NL-to-SQL Analytics Copilot
            </h1>
            <p
              style={{
                margin: 0,
                fontSize: 11,
                color: "var(--text-subtle)",
              }}
            >
              FastAPI · sqlglot validator · read-only execution · self-correction loop
            </p>
          </div>
          <div
            style={{
              fontSize: 11,
              color: "var(--text-muted)",
              display: "flex",
              gap: 16,
            }}
          >
            <span>
              <strong style={{ color: "var(--text)" }}>{turns.length}</strong> question{turns.length === 1 ? "" : "s"}
            </span>
            <span>
              LLM: <strong style={{ color: "var(--text)" }}>glm</strong>
            </span>
          </div>
        </header>

        <ConversationView turns={turns} onUpdateTurn={updateTurn} />
        <QuestionInput onSubmit={submit} disabled={isAsking} />
      </main>
    </div>
  );
}

"use client";

import { useState, type FormEvent } from "react";
import { Send, Sparkles } from "lucide-react";

interface QuestionInputProps {
  onSubmit: (question: string) => void;
  disabled?: boolean;
}

const SUGGESTIONS = [
  "What is the total revenue by region?",
  "How many orders were placed each month in 2025?",
  "Which 5 customers have placed the most orders?",
  "Which products have never been ordered?",
];

export function QuestionInput({ onSubmit, disabled }: QuestionInputProps) {
  const [value, setValue] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const q = value.trim();
    if (!q || disabled) return;
    onSubmit(q);
    setValue("");
  };

  return (
    <div
      style={{
        background: "var(--bg-panel)",
        borderTop: "1px solid var(--border)",
        padding: "16px 24px",
      }}
    >
      <form onSubmit={submit} style={{ display: "flex", gap: 8 }}>
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Ask a question in plain English…"
          disabled={disabled}
          style={{
            flex: 1,
            padding: "12px 16px",
            fontSize: 14,
            border: "1px solid var(--border-strong)",
            borderRadius: 8,
            background: "var(--bg)",
            color: "var(--text)",
            outline: "none",
          }}
          autoFocus
        />
        <button
          type="submit"
          disabled={disabled || !value.trim()}
          style={{
            padding: "12px 20px",
            background: "var(--accent)",
            color: "white",
            border: "none",
            borderRadius: 8,
            fontWeight: 600,
            fontSize: 14,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <Send size={14} />
          Ask
        </button>
      </form>
      <div
        style={{
          marginTop: 8,
          display: "flex",
          gap: 6,
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <span
          style={{
            fontSize: 11,
            color: "var(--text-subtle)",
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}
        >
          <Sparkles size={11} /> Try:
        </span>
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => !disabled && onSubmit(s)}
            disabled={disabled}
            style={{
              padding: "4px 10px",
              fontSize: 12,
              background: "var(--bg-elevated)",
              border: "1px solid var(--border)",
              borderRadius: 12,
              color: "var(--text-muted)",
            }}
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

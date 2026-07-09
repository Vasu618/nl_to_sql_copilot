"use client";

import { useEffect, useState } from "react";
import type { SchemaTable } from "@/types/api";
import { fetchSchema } from "@/lib/api";
import { ChevronDown, ChevronRight, Database, Table2 } from "lucide-react";

interface SchemaSidebarProps {
  onCloseMobile?: () => void;
}

export function SchemaSidebar({ onCloseMobile }: SchemaSidebarProps) {
  const [tables, setTables] = useState<SchemaTable[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let cancelled = false;
    fetchSchema()
      .then((data) => {
        if (!cancelled) {
          setTables(data.tables);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(String(e));
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const toggle = (name: string) =>
    setExpanded((s) => ({ ...s, [name]: !s[name] }));

  return (
    <aside
      style={{
        width: 280,
        minWidth: 280,
        background: "var(--bg-panel)",
        borderRight: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        position: "sticky",
        top: 0,
      }}
    >
      <header
        style={{
          padding: "16px 16px 12px",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <Database size={16} style={{ color: "var(--accent)" }} />
        <strong style={{ fontSize: 14 }}>Schema Browser</strong>
      </header>

      <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
        {loading && (
          <div style={{ padding: "16px", color: "var(--text-muted)", fontSize: 13 }}>
            Loading schema…
          </div>
        )}
        {error && (
          <div style={{ padding: "16px", color: "var(--danger)", fontSize: 13 }}>
            Failed to load schema: {error}
          </div>
        )}
        {!loading && !error && tables.length === 0 && (
          <div style={{ padding: "16px", color: "var(--text-muted)", fontSize: 13 }}>
            No tables found.
          </div>
        )}
        {!loading &&
          tables.map((table) => {
            const isOpen = expanded[table.name] ?? true;
            return (
              <div key={table.name} style={{ marginBottom: 2 }}>
                <button
                  onClick={() => toggle(table.name)}
                  style={{
                    width: "100%",
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "8px 16px",
                    background: "transparent",
                    border: "none",
                    textAlign: "left",
                    color: "var(--text)",
                    fontWeight: 600,
                    fontSize: 13,
                  }}
                >
                  {isOpen ? (
                    <ChevronDown size={14} style={{ color: "var(--text-subtle)" }} />
                  ) : (
                    <ChevronRight size={14} style={{ color: "var(--text-subtle)" }} />
                  )}
                  <Table2 size={14} style={{ color: "var(--accent)" }} />
                  <span>{table.name}</span>
                  <span style={{ marginLeft: "auto", color: "var(--text-subtle)", fontSize: 11, fontWeight: 400 }}>
                    {table.columns.length} cols
                  </span>
                </button>
                {isOpen && (
                  <ul style={{ listStyle: "none", padding: "0 16px 8px 38px", margin: 0 }}>
                    {table.columns.map((col) => (
                      <li
                        key={col.name}
                        style={{
                          padding: "3px 0",
                          fontSize: 12,
                          color: "var(--text-muted)",
                          display: "flex",
                          alignItems: "center",
                          gap: 6,
                        }}
                      >
                        <span style={{ fontFamily: "monospace" }}>{col.name}</span>
                        <span style={{ color: "var(--text-subtle)", fontSize: 11 }}>
                          {col.type}
                        </span>
                        {col.primary_key && (
                          <span
                            style={{
                              fontSize: 10,
                              padding: "1px 5px",
                              background: "var(--accent-soft)",
                              color: "var(--accent)",
                              borderRadius: 3,
                              fontWeight: 600,
                            }}
                          >
                            PK
                          </span>
                        )}
                        {col.foreign_key && (
                          <span
                            style={{
                              fontSize: 10,
                              padding: "1px 5px",
                              background: "var(--bg-elevated)",
                              color: "var(--text-muted)",
                              borderRadius: 3,
                            }}
                            title={`FK -> ${col.foreign_key}`}
                          >
                            FK
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
      </div>

      <footer
        style={{
          padding: "8px 16px",
          borderTop: "1px solid var(--border)",
          fontSize: 11,
          color: "var(--text-subtle)",
        }}
      >
        {tables.length} tables · read-only role
      </footer>
    </aside>
  );
}

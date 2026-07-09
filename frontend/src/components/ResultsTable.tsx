"use client";

import type { AskResponse } from "@/types/api";

interface ResultsTableProps {
  response: AskResponse;
}

function formatCell(v: unknown): string {
  if (v === null) return "NULL";
  if (v === undefined) return "";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") {
    if (Number.isInteger(v)) return v.toLocaleString();
    return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  if (typeof v === "string") {
    // ISO timestamps: shorten to date for display
    if (/^\d{4}-\d{2}-\d{2}T/.test(v)) return v.replace("T", " ").slice(0, 19);
    return v.length > 80 ? v.slice(0, 77) + "…" : v;
  }
  return JSON.stringify(v);
}

export function ResultsTable({ response }: ResultsTableProps) {
  const rows = response.rows;
  const rowCount = response.row_count ?? 0;

  if (!rows || rows.length === 0) {
    return (
      <div
        style={{
          padding: "24px 14px",
          background: "var(--bg-panel)",
          border: "1px solid var(--border)",
          borderRadius: 8,
          textAlign: "center",
          color: "var(--text-muted)",
          fontSize: 13,
        }}
      >
        {rowCount === 0
          ? "Query returned 0 rows."
          : `Query returned ${rowCount} rows (none shown).`}
      </div>
    );
  }

  const columns = Object.keys(rows[0]);
  const showing = rows.length;
  const truncated = response.truncated;

  return (
    <div
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border)",
        borderRadius: 8,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "8px 14px",
          background: "var(--bg-elevated)",
          borderBottom: "1px solid var(--border)",
          fontSize: 12,
          color: "var(--text-muted)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span>
          <strong>{rowCount.toLocaleString()}</strong> row{rowCount === 1 ? "" : "s"}
          {truncated && (
            <span style={{ color: "var(--warning)", marginLeft: 8 }}>
              (truncated at row cap — showing first {showing.toLocaleString()})
            </span>
          )}
        </span>
        <span style={{ fontSize: 11, color: "var(--text-subtle)" }}>
          {columns.length} column{columns.length === 1 ? "" : "s"}
        </span>
      </div>
      <div style={{ overflowX: "auto", maxHeight: 360, overflowY: "auto" }}>
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontSize: 12,
          }}
        >
          <thead style={{ position: "sticky", top: 0 }}>
            <tr>
              <th
                style={{
                  padding: "6px 10px",
                  background: "var(--bg-elevated)",
                  borderBottom: "1px solid var(--border)",
                  textAlign: "right",
                  color: "var(--text-subtle)",
                  fontSize: 10,
                  fontWeight: 500,
                  width: 40,
                }}
              >
                #
              </th>
              {columns.map((c) => (
                <th
                  key={c}
                  style={{
                    padding: "6px 12px",
                    background: "var(--bg-elevated)",
                    borderBottom: "1px solid var(--border)",
                    textAlign: "left",
                    color: "var(--text)",
                    fontWeight: 600,
                    fontFamily: "monospace",
                    fontSize: 11,
                    whiteSpace: "nowrap",
                  }}
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr
                key={i}
                style={{
                  background: i % 2 === 0 ? "var(--bg-panel)" : "var(--bg-elevated)",
                }}
              >
                <td
                  style={{
                    padding: "5px 10px",
                    textAlign: "right",
                    color: "var(--text-subtle)",
                    fontSize: 10,
                    fontFamily: "monospace",
                  }}
                >
                  {i + 1}
                </td>
                {columns.map((c) => (
                  <td
                    key={c}
                    style={{
                      padding: "5px 12px",
                      color: "var(--text)",
                      fontFamily:
                        typeof row[c] === "number" ? "monospace" : "inherit",
                      whiteSpace: "nowrap",
                      maxWidth: 400,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                    title={String(row[c] ?? "")}
                  >
                    {formatCell(row[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

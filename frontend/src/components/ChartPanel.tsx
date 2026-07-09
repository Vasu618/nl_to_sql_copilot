"use client";

import type { AskResponse, ChartType } from "@/types/api";
import { chartTypeLabel } from "@/lib/api";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

interface ChartPanelProps {
  response: AskResponse;
}

const PIE_COLORS = [
  "#2563eb", "#16a34a", "#d97706", "#dc2626", "#7c3aed",
  "#0891b2", "#db2777", "#65a30d", "#ea580c", "#4f46e5",
];

function toNumber(v: unknown): number {
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    const n = parseFloat(v);
    if (!Number.isNaN(n)) return n;
  }
  return 0;
}

export function ChartPanel({ response }: ChartPanelProps) {
  const chartType: ChartType = response.suggested_chart_type || "none";
  const rows = response.rows || [];

  if (chartType === "none" || rows.length === 0) {
    return null; // No chart — let the results table and answer panel carry it.
  }

  // For all chart types, we assume the result has at least 2 columns.
  // The first column is the label (category, date, etc.); the second is the value.
  // For "table" we also return null — the results table handles that case.
  if (chartType === "table") {
    return null;
  }

  const columns = Object.keys(rows[0]);
  if (columns.length < 2) {
    return null;
  }
  const labelKey = columns[0];
  const valueKey = columns[1];
  const data = rows.map((r) => ({
    label: String(r[labelKey] ?? ""),
    value: toNumber(r[valueKey]),
  }));

  return (
    <div
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: "12px 14px",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 8,
        }}
      >
        <strong style={{ fontSize: 13 }}>Chart</strong>
        <span
          style={{
            fontSize: 11,
            color: "var(--text-subtle)",
            padding: "2px 8px",
            background: "var(--bg-elevated)",
            borderRadius: 10,
          }}
          title={chartTypeLabel(chartType)}
        >
          {chartType} · {chartTypeLabel(chartType)}
        </span>
      </div>

      <div style={{ width: "100%", height: 260 }}>
        <ResponsiveContainer>
          {chartType === "bar" ? (
            <BarChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 11, fill: "#64748b" }}
                interval={0}
                angle={data.length > 5 ? -15 : 0}
                textAnchor={data.length > 5 ? "end" : "middle"}
                height={data.length > 5 ? 50 : 30}
              />
              <YAxis tick={{ fontSize: 11, fill: "#64748b" }} />
              <Tooltip
                formatter={(v) => (typeof v === "number" ? v.toLocaleString() : String(v))}
                contentStyle={{
                  fontSize: 12,
                  borderRadius: 6,
                  border: "1px solid #e2e8f0",
                }}
              />
              <Bar dataKey="value" fill="#2563eb" radius={[4, 4, 0, 0]} />
            </BarChart>
          ) : chartType === "line" ? (
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 11, fill: "#64748b" }}
                interval="preserveStartEnd"
              />
              <YAxis tick={{ fontSize: 11, fill: "#64748b" }} />
              <Tooltip
                formatter={(v) => (typeof v === "number" ? v.toLocaleString() : String(v))}
                contentStyle={{
                  fontSize: 12,
                  borderRadius: 6,
                  border: "1px solid #e2e8f0",
                }}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke="#2563eb"
                strokeWidth={2}
                dot={{ r: 3, fill: "#2563eb" }}
              />
            </LineChart>
          ) : (
            // pie
            <PieChart>
              <Pie
                data={data}
                dataKey="value"
                nameKey="label"
                cx="50%"
                cy="50%"
                outerRadius={90}
                label={(props: { name?: string }) => props.name ?? ""}
                labelLine={false}
              >
                {data.map((_, i) => (
                  <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                formatter={(v) => (typeof v === "number" ? v.toLocaleString() : String(v))}
                contentStyle={{
                  fontSize: 12,
                  borderRadius: 6,
                  border: "1px solid #e2e8f0",
                }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
            </PieChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}

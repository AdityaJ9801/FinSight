import { useState, useMemo } from "react";
import { Columns2, Rows2, Search, Layers } from "lucide-react";
import { useDataExplorer } from "../lib/hooks";
import { formatInrCompact, formatPeriodShort } from "../lib/format";
import type { Job, DataExplorerAttributeRow, DataExplorerColumn } from "../lib/types";
import { EmptyState, Skeleton } from "./ui";

const pct = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : `${v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(digits)}%`;

const money = (v: number | null | undefined) =>
  v === null || v === undefined ? "–" : formatInrCompact(v);

const fy = (iso: string) => formatPeriodShort(iso);

export function DataExplorer({ job }: { job: Job }) {
  const { data, isLoading, error } = useDataExplorer(job.id, job);
  const [selectedSheet, setSelectedSheet] = useState<string>("All Attributes");
  const [format, setFormat] = useState<"row" | "column">("row");
  const [displayMode, setDisplayMode] = useState<"amounts" | "change">("amounts");
  const [search, setSearch] = useState("");

  const sheets = data?.sheets || [];
  const activeSheet = sheets.includes(selectedSheet) ? selectedSheet : sheets[0] || "All Attributes";

  // Filtered rows for Row Format
  const rows: DataExplorerAttributeRow[] = useMemo(() => {
    if (!data?.row_format) return [];
    const sourceRows = activeSheet === "All Attributes"
      ? (data.row_format.all || [])
      : (data.row_format.sheets?.[activeSheet] || []);

    if (!search.trim()) return sourceRows;
    const q = search.toLowerCase();
    return sourceRows.filter(
      (r: DataExplorerAttributeRow) =>
        r.attribute_name.toLowerCase().includes(q) ||
        r.account_id.toLowerCase().includes(q) ||
        (r.account_name && r.account_name.toLowerCase().includes(q)) ||
        (r.sheet && r.sheet.toLowerCase().includes(q))
    );
  }, [data, activeSheet, search]);

  // Data for Column Format
  const columnData = useMemo(() => {
    if (!data?.column_format?.sheets) return null;
    const colSheet = data.column_format.sheets[activeSheet];
    if (!colSheet) return null;

    let cols = colSheet.columns;
    if (search.trim()) {
      const q = search.toLowerCase();
      cols = cols.filter(
        (c: DataExplorerColumn) =>
          c.key === "period" ||
          c.label.toLowerCase().includes(q) ||
          (c.account_id && c.account_id.toLowerCase().includes(q))
      );
    }
    return {
      columns: cols,
      rows: colSheet.rows,
    };
  }, [data, activeSheet, search]);

  if (isLoading) {
    return (
      <div className="panel" style={{ marginTop: 20 }}>
        <Skeleton h={30} w="40%" />
        <div style={{ height: 16 }} />
        <Skeleton h={320} />
      </div>
    );
  }

  if (error || !data || !data.periods.length) {
    return (
      <EmptyState title="No extracted attributes found">
        Uploaded files have not produced structured financial facts yet, or the data stage is still processing.
      </EmptyState>
    );
  }

  const periods = data.periods;

  return (
    <div className="data-explorer-panel">
      {/* Header bar */}
      <div className="section-head" style={{ marginBottom: 16 }}>
        <div>
          <h2 className="panel-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Layers size={18} />
            <span>Dataset Attributes &amp; Line Items Explorer</span>
          </h2>
          <span className="muted small">
            Discovered <strong>{data.summary.total_attributes}</strong> unique attributes and <strong>{data.summary.total_facts}</strong> values across <strong>{periods.length}</strong> reporting periods.
          </span>
        </div>

        {/* Controls: Format toggle & sheet picker */}
        <div className="stmt-controls" style={{ alignItems: "center" }}>
          {/* Format Toggle: Row vs Column */}
          <div className="seg" role="tablist" aria-label="Format Layout">
            <button
              type="button"
              role="tab"
              aria-selected={format === "row"}
              className={format === "row" ? "seg-on" : ""}
              onClick={() => setFormat("row")}
              style={{ display: "flex", alignItems: "center", gap: 5 }}
            >
              <Rows2 size={14} />
              <span>Row Format (Horizontal)</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={format === "column"}
              className={format === "column" ? "seg-on" : ""}
              onClick={() => setFormat("column")}
              style={{ display: "flex", alignItems: "center", gap: 5 }}
            >
              <Columns2 size={14} />
              <span>Column Format (Tabular)</span>
            </button>
          </div>

          {/* If in Row format, allow toggle between Amounts and YoY Change */}
          {format === "row" && (
            <div className="seg" role="tablist" aria-label="Display Mode">
              <button
                type="button"
                className={displayMode === "amounts" ? "seg-on" : ""}
                onClick={() => setDisplayMode("amounts")}
              >
                Amounts
              </button>
              <button
                type="button"
                className={displayMode === "change" ? "seg-on" : ""}
                onClick={() => setDisplayMode("change")}
              >
                YoY Change %
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Sheet / Category Filter and Search Bar */}
      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", gap: 12, marginBottom: 14 }}>
        <div className="seg" role="tablist" aria-label="Filter Sheet">
          {sheets.map((s: string) => (
            <button
              key={s}
              type="button"
              className={activeSheet === s ? "seg-on" : ""}
              onClick={() => setSelectedSheet(s)}
            >
              {s}
            </button>
          ))}
        </div>

        <div style={{ position: "relative", minWidth: 240, maxWidth: 360, flex: 1 }}>
          <Search size={14} style={{ position: "absolute", left: 10, top: 10, color: "var(--graphite)" }} />
          <input
            type="text"
            className="input"
            style={{ width: "100%", paddingLeft: 30, fontSize: 13, height: 34 }}
            placeholder="Search attributes, lines, or accounts..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {/* ------------------------------------------------------------- */}
      {/* 1. ROW FORMAT VIEW (Attributes as rows, periods as columns)  */}
      {/* ------------------------------------------------------------- */}
      {format === "row" && (
        <div className="spread-wrap table-card">
          <table className="spread">
            <thead>
              <tr>
                <th scope="col" style={{ minWidth: 260 }}>Attribute / Statement Line</th>
                <th scope="col" style={{ minWidth: 140 }}>Section</th>
                <th scope="col" style={{ minWidth: 160 }}>Canonical Account</th>
                {periods.map((p: string) => (
                  <th key={p} scope="col" className="num" style={{ minWidth: 110 }}>
                    {fy(p)}
                  </th>
                ))}
                {periods.length > 1 && (
                  <th scope="col" className="num" style={{ minWidth: 110 }}>
                    YoY % ({fy(periods[periods.length - 1])})
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, idx) => {
                const latestPeriod = periods[periods.length - 1];
                const change = r.change_pct?.[latestPeriod];
                const isTotal = /total|net profit|profit after tax|^pat$|equity & liabilities/i.test(r.attribute_name);
                return (
                  <tr key={`${r.sheet}-${r.attribute_name}-${idx}`} className={isTotal ? "stmt-total" : ""}>
                    <th scope="row">
                      <span style={{ fontWeight: isTotal ? 600 : 500 }}>{r.attribute_name}</span>
                    </th>
                    <td className="muted small">{r.sheet}</td>
                    <td>
                      <code style={{ fontSize: 11, background: "var(--paper)", padding: "2px 5px", borderRadius: 3 }}>
                        {r.account_id}
                      </code>
                    </td>
                    {periods.map((p: string) => {
                      const val = r.values?.[p];
                      const chg = r.change_pct?.[p];
                      if (displayMode === "change") {
                        const cls = typeof chg === "number" ? (chg >= 0 ? "delta-good" : "delta-bad") : "";
                        return (
                          <td key={p} className={`num ${cls}`}>
                            {pct(chg)}
                          </td>
                        );
                      }
                      const isNegative = typeof val === "number" && val < 0;
                      return (
                        <td key={p} className={`num ${isNegative ? "neg" : ""}`}>
                          {money(val)}
                        </td>
                      );
                    })}
                    {periods.length > 1 && (
                      <td className={`num ${typeof change === "number" ? (change >= 0 ? "delta-good" : "delta-bad") : ""}`}>
                        {pct(change)}
                      </td>
                    )}
                  </tr>
                );
              })}
              {!rows.length && (
                <tr>
                  <td colSpan={periods.length + (periods.length > 1 ? 4 : 3)} className="muted center" style={{ padding: 24 }}>
                    No attributes found matching &ldquo;{search}&rdquo;.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* 2. COLUMN FORMAT VIEW (Periods as rows, attributes as columns) */}
      {/* ------------------------------------------------------------- */}
      {format === "column" && columnData && (
        <div className="spread-wrap table-card">
          <table className="spread">
            <thead>
              <tr>
                {columnData.columns.map((col: DataExplorerColumn) => (
                  <th
                    key={col.key}
                    scope="col"
                    className={col.type === "numeric" ? "num" : ""}
                    style={{ minWidth: col.key === "period" ? 120 : 180, whiteSpace: "nowrap" }}
                  >
                    <span>{col.label}</span>
                    {col.account_id && (
                      <span className="mini-sub" style={{ fontSize: 10 }}>
                        {col.account_id}
                      </span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {columnData.rows.map((rowItem: Record<string, any>, idx: number) => (
                <tr key={rowItem.period || idx}>
                  {columnData.columns.map((col: DataExplorerColumn) => {
                    const val = rowItem[col.key];
                    if (col.key === "period") {
                      return (
                        <th key={col.key} scope="row" style={{ whiteSpace: "nowrap" }}>
                          {formatPeriodShort(val)}
                        </th>
                      );
                    }
                    const numVal = typeof val === "number" ? val : null;
                    const isNegative = numVal !== null && numVal < 0;
                    return (
                      <td key={col.key} className={`num ${isNegative ? "neg" : ""}`}>
                        {money(numVal)}
                      </td>
                    );
                  })}
                </tr>
              ))}
              {!columnData.rows.length && (
                <tr>
                  <td colSpan={columnData.columns.length} className="muted center" style={{ padding: 24 }}>
                    No period records found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Explanatory footer note */}
      <div className="source-note" style={{ marginTop: 10, display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <span>
          Showing actual attributes extracted from source files. Toggle between <strong>Row format</strong> (standard statement layout) and <strong>Column format</strong> (multi-attribute tabular layout).
        </span>
        <span className="muted">
          {rows.length} attributes displayed
        </span>
      </div>
    </div>
  );
}

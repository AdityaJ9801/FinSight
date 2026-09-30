from __future__ import annotations

from datetime import date

from app.agents.base import AgentResult, ArtifactRef, Status, TaskSpec, WorkerAgent
from app.agents.schemas import ChartCaptionSet
from app.domain.facts import load_facts_by_period
from app.llm_gateway import prompts
from app.llm_gateway.prompt_utils import embed_json
from app.models.metric import Metric
from app.orchestrator import blackboard
from app.tools.calc.health_score import compute_health_score
from app.tools.chart_render import fmt_value
from app.utils.ids import new_id
from app.utils.money import display_scale_for, set_thread_scale

# Chart selection is deterministic (design doc §2 principle 3: "deterministic first") --
# which charts exist, what they plot, their benchmarks and their one-line takeaway are all
# computed here from validated data. The LLM only writes the explanatory caption.

METRIC_LABELS = {
    "gross_profit_pct": "Gross margin", "ebitda_margin": "EBITDA margin", "net_profit_margin": "Net margin",
    "current_ratio": "Current ratio", "quick_ratio": "Quick ratio", "cash_ratio": "Cash ratio",
    "debt_to_equity": "Debt / equity", "net_debt_to_ebitda": "Net debt / EBITDA",
    "interest_coverage": "Interest coverage", "dscr": "Debt service coverage",
    "dso": "Debtor days (DSO)", "dio": "Inventory days (DIO)", "dpo": "Payable days (DPO)",
    "cash_conversion_cycle": "Cash conversion cycle", "revenue_growth_yoy": "Revenue growth",
    "ebitda_growth_yoy": "EBITDA growth", "pat_growth_yoy": "PAT growth", "roe": "ROE", "roce": "ROCE",
    "asset_turnover": "Asset turnover", "ocf_to_pat": "Cash conversion (OCF / PAT)",
}
METRIC_UNITS = {
    "gross_profit_pct": "%", "ebitda_margin": "%", "net_profit_margin": "%", "revenue_growth_yoy": "%",
    "ebitda_growth_yoy": "%", "pat_growth_yoy": "%", "roe": "%", "roce": "%", "dso": "days", "dio": "days",
    "dpo": "days", "cash_conversion_cycle": "days",
}

# Where each rupee of revenue goes (common-size P&L), in presentation order.
_REVENUE_USES = [("Materials", "PL.COGS"), ("Stock-in-trade", "PL.PURCHASES_STOCK_IN_TRADE"),
                 ("Inventory change", "PL.CHANGES_IN_INVENTORY"), ("Employees", "PL.EMPLOYEE_COST"),
                 ("Other expenses", "PL.OTHER_EXPENSES"), ("Depreciation", "PL.DEPRECIATION"),
                 ("Finance costs", "PL.FINANCE_COST"), ("Tax", "PL.TAX"), ("Net profit", "PL.PAT")]
_ASSETS = [("Cash", "BS.CA.CASH"), ("Receivables", "BS.CA.TRADE_RECEIVABLES"), ("Inventory", "BS.CA.INVENTORY"),
           ("Other current", "BS.CA.OTHER"), ("Fixed assets (PPE)", "BS.NCA.PPE"), ("Other non-current", "BS.NCA.OTHER")]
_FUNDING = [("Equity", "BS.EQ.TOTAL"), ("Long-term debt", "BS.NCL.LONG_TERM_BORROWINGS"),
            ("Short-term debt", "BS.CL.SHORT_TERM_BORROWINGS"), ("Trade payables", "BS.CL.TRADE_PAYABLES"),
            ("Other current liab.", "BS.CL.OTHER"), ("Other non-current liab.", "BS.NCL.OTHER")]


def period_label(p: date | str, forecast: bool = False) -> str:
    d = p if isinstance(p, date) else date.fromisoformat(str(p)[:10])
    return d.strftime("%b %Y") + (" (F)" if forecast else "")


def _num(v):
    return v is not None and v == v


def change_phrase(name: str, values: list, unit: str | None) -> str:
    """'Gross margin 40.0% → 41.7% (+1.7 pp)' across the first and last available points."""
    pts = [v for v in values if _num(v)]
    if not pts:
        return ""
    if len(pts) == 1:
        return f"{name} {fmt_value(pts[0], unit)}"
    a, b = pts[0], pts[-1]
    if unit == "%":
        delta = f"{(b - a) * 100:+.1f} pp"
    elif unit == "x":
        delta = f"{b - a:+.2f}x"
    elif unit == "days":
        delta = f"{b - a:+.1f} days"
    else:
        delta = f"{(b - a) / abs(a) * 100:+.1f}%" if a else ""
    return f"{name} {fmt_value(a, unit)} → {fmt_value(b, unit)}" + (f" ({delta})" if delta else "")


class ChartSpecAgent(WorkerAgent):
    name = "chart_spec"
    allowed_tools = ["chart.render"]

    def execute(self, spec: TaskSpec) -> AgentResult:
        dsv = spec.params["dataset_version_id"]
        self.job_id = spec.job_id
        self.facts = load_facts_by_period(dsv)
        self.periods = sorted(self.facts)
        self.labels = [period_label(p) for p in self.periods]
        rows = Metric.query.filter_by(dataset_version=dsv).all()
        self.metrics: dict[str, dict[date, float]] = {}
        for m in rows:
            if m.value is not None:
                self.metrics.setdefault(m.metric_code, {})[m.period_end] = float(m.value)
        self.analysis = blackboard.read(spec.job_id, "detailed_analysis") or {}

        builders = [
            self._health_scorecard, self._revenue_ebitda_combo, self._margin_profile, self._revenue_uses,
            self._liquidity, self._leverage_panels, self._working_capital_cycle, self._cash_flow_profile,
            self._growth, self._returns_panels, self._forecast, self._profit_bridge, self._dupont_panels,
            self._balance_sheet_structure, self._bank_flows, self._counterparty_concentration,
        ]
        charts: list[dict] = []
        failures = []
        # Every amount on axes, labels and takeaways in the documents' own unit (crores for a
        # crore filing), matching the tables and narrative.
        set_thread_scale(display_scale_for(dsv))
        try:
            for build in builders:
                try:
                    chart = build()
                except Exception as exc:  # noqa: BLE001 -- one chart's bad data must not drop the rest
                    failures.append(f"{build.__name__}: {exc}")
                    continue
                if chart:
                    charts.append(chart)
        finally:
            set_thread_scale(None)

        if charts:
            self._caption_charts(charts)
        uri = blackboard.write(spec.job_id, "charts", charts)
        return AgentResult(
            task_id=spec.task_id, status=Status.DONE if not failures else Status.PARTIAL,
            outputs=[ArtifactRef(id="charts", kind="chart", uri=uri, row_count=len(charts))],
            summary=f"Rendered {len(charts)} chart(s)" + (f"; skipped {len(failures)}: {'; '.join(failures)}" if failures else "."),
            confidence=0.9 if not failures else 0.7,
        )

    # ---------------------------------------------------------------- helpers

    def _series(self, codes: list[str]) -> dict[str, list]:
        out = {}
        for code in codes:
            by_p = self.metrics.get(code, {})
            vals = [by_p.get(p, float("nan")) for p in self.periods]
            if any(_num(v) for v in vals):
                out[METRIC_LABELS.get(code, code)] = vals
        return out

    def _fact_series(self, account_id: str) -> list:
        return [self.facts[p].get(account_id, float("nan")) for p in self.periods]

    def _trend_kind(self) -> str:
        # Two or three points read better as grouped bars than as a "trend" line.
        return "bar" if len(self.periods) <= 3 else "line"

    def _render(self, section_key: str, title: str, chart_type: str, labels: list[str], series: dict,
                unit: str | None = None, takeaway: str = "", options: dict | None = None) -> dict:
        chart_id = new_id("chart_")
        rendered = self.call_tool("chart.render", job_id=self.job_id, chart_id=chart_id, title=title,
                                  chart_type=chart_type, labels=labels, series=series, unit=unit,
                                  subtitle=takeaway or None, options=options or {})
        return {"chart_id": chart_id, "title": title, "section_key": section_key, "takeaway": takeaway,
                "caption": "", **rendered}

    # ---------------------------------------------------------------- charts

    def _health_scorecard(self):
        if not self.periods:
            return None
        latest = self.periods[-1]
        latest_metrics = {c: v[latest] for c, v in self.metrics.items() if latest in v}
        health = compute_health_score(latest_metrics)
        items = [b for b in health["breakdown"] if b["included"]]
        if not items:
            return None
        labels = [f"{METRIC_LABELS.get(b['metric_code'], b['metric_code'])} "
                  f"({fmt_value(latest_metrics[b['metric_code']], METRIC_UNITS.get(b['metric_code'], 'x'))})"
                  for b in items]
        points = [b["points"] for b in items]
        colors = ["#16a34a" if p >= b["weight"] else "#f59e0b" if p / b["weight"] >= 0.5 else "#dc2626"
                  for p, b in zip(points, items)]
        weakest = min(items, key=lambda b: b["points"] / b["weight"])
        return self._render("executive_summary", f"Financial Health Scorecard — {health['score']}/100 ({health['rating']})",
                            "hbar", labels, {"Points scored": points}, unit="pts",
                            takeaway=f"Points earned per driver (dashed = maximum). Weakest driver: "
                                     f"{METRIC_LABELS.get(weakest['metric_code'], weakest['metric_code'])}.",
                            options={"hbar_colors": colors, "max_values": [b["weight"] for b in items]})

    def _revenue_ebitda_combo(self):
        rev = self._fact_series("PL.REVENUE")
        ebitda = [self.metrics.get("ebitda", {}).get(p, float("nan")) for p in self.periods]
        margin = [self.metrics.get("ebitda_margin", {}).get(p, float("nan")) for p in self.periods]
        if not any(_num(v) for v in rev):
            return None
        series = {"Revenue": rev}
        if any(_num(v) for v in ebitda):
            series["EBITDA"] = ebitda
        secondary = {"series": {"EBITDA margin": margin}, "unit": "%"} if any(_num(v) for v in margin) else None
        take = "; ".join(t for t in [change_phrase("Revenue", rev, "INR"), change_phrase("EBITDA margin", margin, "%")] if t)
        return self._render("profitability", "Revenue, EBITDA & EBITDA Margin", "bar", self.labels, series, unit="INR",
                            takeaway=take, options={"secondary": secondary} if secondary else {})

    def _margin_profile(self):
        series = self._series(["gross_profit_pct", "ebitda_margin", "net_profit_margin"])
        if not series:
            return None
        take = "; ".join(change_phrase(k, v, "%") for k, v in series.items())
        return self._render("profitability", "Margin Profile", self._trend_kind(), self.labels, series, unit="%",
                            takeaway=take)

    def _revenue_uses(self):
        """Every rupee of income (revenue + other income) split into what it paid for, with
        what's left as profit on top -- one base for both the bars and the takeaway."""
        income = [(r if _num(r) else 0.0) + (o if _num(o) else 0.0)
                  for r, o in zip(self._fact_series("PL.REVENUE"), self._fact_series("PL.OTHER_INCOME"))]
        if not any(income):
            return None
        series = {}
        for label, acc in _REVENUE_USES:
            vals = self._fact_series(acc)
            if any(_num(v) and v > 0 for v in vals):
                series[label] = [(v / t) if _num(v) and v > 0 and t else 0.0 for v, t in zip(vals, income)]
        if len(series) < 2:
            return None
        residual = [1.0 - sum(v[i] for v in series.values()) for i in range(len(income))]
        if any(abs(r) > 0.005 for r in residual):
            series["Other / unallocated"] = residual
        biggest = max((k for k in series if k != "Net profit"), key=lambda k: series[k][-1])
        take = f"{self.labels[-1]}: {biggest} takes {fmt_value(series[biggest][-1], '%')} of every rupee of income"
        if "Net profit" in series:
            take += f"; {fmt_value(series['Net profit'][-1], '%')} is kept as profit"
            if len(income) > 1:
                take += f" (was {fmt_value(series['Net profit'][0], '%')})"
        return self._render("cost_structure", "Where Each Rupee of Income Goes", "stacked_bar", self.labels, series,
                            unit="%", takeaway=take)

    def _liquidity(self):
        series = self._series(["current_ratio", "quick_ratio", "cash_ratio"])
        if not series:
            return None
        take = "; ".join(change_phrase(k, v, "x") for k, v in series.items() if k != "Cash ratio")
        return self._render("liquidity", "Liquidity Ratios vs. Benchmarks", "bar", self.labels, series, unit="x",
                            takeaway=take, options={"reference_lines": [
                                {"value": 1.0, "label": "Minimum", "color": "#dc2626"},
                                {"value": 1.33, "label": "Lender comfort", "color": "#16a34a"}]})

    def _leverage_panels(self):
        left = self._series(["debt_to_equity", "net_debt_to_ebitda"])
        right = self._series(["interest_coverage", "dscr"])
        panels = []
        if left:
            panels.append({"title": "Leverage (lower is safer)", "chart_type": "bar", "series": left, "unit": "x",
                           "reference_lines": [{"value": 1.0, "label": "Caution", "color": "#f59e0b"}]})
        if right:
            panels.append({"title": "Debt service (higher is safer)", "chart_type": "bar", "series": right, "unit": "x",
                           "reference_lines": [{"value": 1.5, "label": "Lender floor", "color": "#dc2626"}],
                           "options": {"colors": {"Interest coverage": "#7c3aed", "Debt service coverage": "#0891b2"}}})
        if not panels:
            return None
        take = "; ".join(change_phrase(k, v, "x") for s in (left, right) for k, v in list(s.items())[:1])
        return self._render("leverage", "Leverage & Debt-Service Capacity", "panels", self.labels, {}, takeaway=take,
                            options={"panels": panels})

    def _working_capital_cycle(self):
        dso, dio, dpo = (self._series([c]) for c in ("dso", "dio", "dpo"))
        ccc = self._series(["cash_conversion_cycle"])
        if not (dso or dio):
            return None
        series = {**dso, **dio}
        for k, v in dpo.items():
            series[k + " (funding)"] = [-x if _num(x) else x for x in v]
        take = change_phrase("Cash conversion cycle", next(iter(ccc.values())), "days") if ccc else ""
        return self._render("working_capital", "Working Capital Cycle (Days)", "stacked_bar", self.labels, series,
                            unit="days", takeaway=take + ("; payables (negative) fund part of the cycle" if dpo else ""),
                            options={"overlay": ccc,
                                     "colors": {"Debtor days (DSO)": "#2563eb", "Inventory days (DIO)": "#f59e0b",
                                                "Payable days (DPO) (funding)": "#16a34a"}})

    def _cash_flow_profile(self):
        series = {}
        for label, acc in [("Operating", "CF.OPERATING"), ("Investing", "CF.INVESTING"), ("Financing", "CF.FINANCING")]:
            vals = self._fact_series(acc)
            if any(_num(v) for v in vals):
                series[label] = vals
        fcf = [self.metrics.get("free_cash_flow", {}).get(p, float("nan")) for p in self.periods]
        if any(_num(v) for v in fcf):
            series["Free cash flow (OCF - capex)"] = fcf
        else:
            # No capex line: show post-investment cash flow under its real name -- never as FCF.
            after = [self.metrics.get("net_cash_after_investing", {}).get(p, float("nan")) for p in self.periods]
            if any(_num(v) for v in after):
                series["Net cash after all investing"] = after
        if len(series) < 2:
            return None
        conv = self._series(["ocf_to_pat"])
        take = "; ".join(t for t in [
            change_phrase("Operating cash flow", series.get("Operating", []), "INR"),
            change_phrase("Free cash flow", fcf, "INR") if any(_num(v) for v in fcf) else "",
            change_phrase("OCF / PAT", next(iter(conv.values())), "x") if conv else ""] if t)
        return self._render("working_capital", "Cash Flow Profile", "bar", self.labels, series, unit="INR", takeaway=take,
                            options={"secondary": {"series": conv, "unit": "x"} if conv else None,
                                     "colors": {"Operating": "#16a34a", "Investing": "#f59e0b", "Financing": "#64748b",
                                                "Free cash flow (OCF - capex)": "#2563eb",
                                                "Net cash after all investing": "#94a3b8"}})

    def _growth(self):
        series = self._series(["revenue_growth_yoy", "ebitda_growth_yoy", "pat_growth_yoy"])
        idx = [i for i, p in enumerate(self.periods) if any(_num(v[i]) for v in series.values())]
        if not idx:
            return None
        labels = [self.labels[i] for i in idx]
        series = {k: [v[i] for i in idx] for k, v in series.items()}
        latest = {k: v[-1] for k, v in series.items() if _num(v[-1])}
        take = ", ".join(f"{k} {fmt_value(v, '%')}" for k, v in latest.items())
        if "PAT growth" in latest and "Revenue growth" in latest:
            lever = "ahead of" if latest["PAT growth"] > latest["Revenue growth"] else "behind"
            take += f" — profit growing {lever} sales (operating leverage)"
        return self._render("growth_returns", "Year-over-Year Growth", "bar", labels, series, unit="%",
                            takeaway=f"Latest: {take}")

    def _returns_panels(self):
        pct = self._series(["roe", "roce"])
        turn = self._series(["asset_turnover"])
        panels = []
        if pct:
            panels.append({"title": "Returns on capital", "chart_type": self._trend_kind(), "series": pct, "unit": "%"})
        if turn:
            panels.append({"title": "Asset turnover", "chart_type": "bar", "series": turn, "unit": "x",
                           "options": {"colors": {"Asset turnover": "#0891b2"}}})
        if not panels:
            return None
        take = "; ".join(change_phrase(k, v, "%") for k, v in pct.items())
        return self._render("growth_returns", "Returns on Capital & Asset Efficiency", "panels", self.labels, {},
                            takeaway=take, options={"panels": panels})

    def _forecast(self):
        bands = blackboard.read(self.job_id, "forecast") or {}
        panels = []
        takes = []
        for acc, name in [("PL.REVENUE", "Revenue"), ("PL.PAT", "PAT")]:
            b = bands.get(acc)
            actual = self._fact_series(acc)
            if not b or not any(_num(v) for v in actual):
                continue
            fperiods = [date.fromisoformat(p) for p in b["periods"]]
            labels = self.labels + [period_label(p, forecast=True) for p in fperiods]
            n_act = len(self.periods)
            last = actual[-1]
            act = actual + [float("nan")] * len(fperiods)
            fc = [float("nan")] * (n_act - 1) + [last] + list(b["forecast"])
            lo = [float("nan")] * (n_act - 1) + [last] + list(b["lower"])
            hi = [float("nan")] * (n_act - 1) + [last] + list(b["upper"])
            panels.append({"title": f"{name} ({b['method'].replace('_', ' ')})", "chart_type": "band_line", "labels": labels,
                           "series": {f"{name} actual": act, f"{name} forecast": fc}, "unit": "INR",
                           "options": {"dashed": [f"{name} forecast"], "bands": {f"{name} forecast": {"lower": lo, "upper": hi}},
                                       "split_at": n_act - 1,
                                       "colors": {f"{name} actual": "#2563eb" if name == "Revenue" else "#16a34a",
                                                  f"{name} forecast": "#2563eb" if name == "Revenue" else "#16a34a"}}})
            takes.append(f"{name} {fmt_value(last, 'INR')} → {fmt_value(b['forecast'][-1], 'INR')} by "
                         f"{period_label(fperiods[-1])}")
        if not panels:
            return None
        return self._render("forecast", "Revenue & Profit Outlook (with forecast range)", "panels", self.labels, {},
                            takeaway="; ".join(takes) + " — shaded area is the forecast uncertainty range",
                            options={"panels": panels})

    def _profit_bridge(self):
        bridge = self.analysis.get("profit_bridge")
        if not bridge:
            return None
        steps = [s for s in bridge["steps"] if s["kind"] != "end"]
        deltas = sorted((s for s in steps if s["kind"] == "delta"), key=lambda s: s["amount"])
        biggest_drag, biggest_lift = deltas[0], deltas[-1]
        take = (f"PAT {fmt_value(steps[0]['amount'], 'INR')} → {fmt_value(bridge['steps'][-1]['amount'], 'INR')}; "
                f"biggest lift: {biggest_lift['label']} ({fmt_value(biggest_lift['amount'], 'INR')}), "
                f"biggest drag: {biggest_drag['label']} ({fmt_value(biggest_drag['amount'], 'INR')})")
        if bridge.get("reconciled") is False:
            take += " — ⚠ P&L does not reconcile; see Data Diagnostic"
        labels = [f"PAT {period_label(bridge['from_period'])}"] + [s["label"] for s in steps[1:]]
        return self._render("detailed_analysis", "PAT Bridge — What Moved Profit", "waterfall", labels,
                            {"PAT": [s["amount"] for s in steps]}, unit="INR", takeaway=take,
                            options={"closing_label": f"PAT {period_label(bridge['to_period'])}"})

    def _dupont_panels(self):
        rows = self.analysis.get("dupont") or []
        if not rows:
            return None
        labels = [period_label(r["period"]) for r in rows]
        spec = [("Net margin", "net_margin", "%", "#2563eb"), ("Asset turnover", "asset_turnover", "x", "#0891b2"),
                ("Equity multiplier (leverage)", "equity_multiplier", "x", "#f59e0b"), ("ROE", "roe", "%", "#16a34a")]
        panels = [{"title": t, "chart_type": "bar", "labels": labels, "series": {t: [r[k] for r in rows]}, "unit": u,
                   "options": {"colors": {t: c}}} for t, k, u, c in spec]
        take = change_phrase("ROE", [r["roe"] for r in rows], "%")
        if len(rows) >= 2:
            moves = {t: rows[-1][k] / rows[-2][k] - 1 for t, k, _u, _c in spec[:3] if rows[-2][k]}
            driver = max(moves, key=lambda t: abs(moves[t]))
            take += f", driven mostly by {driver.lower()} ({moves[driver] * 100:+.1f}%)"
        return self._render("detailed_analysis", "DuPont ROE Decomposition", "panels", labels, {}, takeaway=take,
                            options={"panels": panels})

    def _balance_sheet_structure(self):
        """Shares of the STATED totals (total assets; total equity and liabilities) -- the
        same base as the supporting tables -- with anything the named lines don't cover shown
        as its own segment. Normalising by the sum of whatever lines happened to be mapped
        made this chart say PPE was ~20% of assets while the table (correctly) said 40%."""
        def shares(items, total_account):
            totals = self._fact_series(total_account)
            if not any(_num(t) and t for t in totals):
                return None
            out = {}
            for label, acc in items:
                vals = self._fact_series(acc)
                if any(_num(v) and v > 0 for v in vals):
                    out[label] = [(v / t) if _num(v) and _num(t) and t else 0.0 for v, t in zip(vals, totals)]
            rest = [1.0 - sum(v[i] for v in out.values()) for i in range(len(totals))]
            if any(r > 0.005 for r in rest):
                out["Not separately reported"] = [max(r, 0.0) for r in rest]
            return out

        assets, funding = shares(_ASSETS, "BS.TOTAL_ASSETS"), shares(_FUNDING, "BS.TOTAL_EQUITY_LIAB")
        if not assets or not funding or len(assets) < 2 or len(funding) < 2:
            return None
        take = (f"{self.labels[-1]}: equity funds {fmt_value(funding.get('Equity', [0.0])[-1], '%')} of total "
                f"equity & liabilities; fixed assets (PPE) are {fmt_value(assets.get('Fixed assets (PPE)', [0.0])[-1], '%')} "
                f"of total assets")
        grey = {"Not separately reported": "#e5e7eb"}
        return self._render("detailed_analysis", "Balance Sheet Structure", "panels", self.labels, {}, takeaway=take,
                            options={"panels": [
                                {"title": "What the business owns (% of total assets)", "chart_type": "stacked_bar",
                                 "unit": "%", "series": assets,
                                 "options": {"colors": {"Cash": "#0ea5e9", "Receivables": "#2563eb", "Inventory": "#f59e0b",
                                                        "Other current": "#a3a3a3", "Fixed assets (PPE)": "#7c3aed",
                                                        "Other non-current": "#c4b5fd", **grey}}},
                                {"title": "How it is funded (% of total equity & liabilities)", "chart_type": "stacked_bar",
                                 "unit": "%", "series": funding,
                                 "options": {"colors": {"Equity": "#16a34a", "Long-term debt": "#dc2626",
                                                        "Short-term debt": "#f97316", "Trade payables": "#2563eb",
                                                        "Other current liab.": "#64748b",
                                                        "Other non-current liab.": "#94a3b8", **grey}}}]})

    def _bank_flows(self):
        monthly = (self.analysis.get("bank") or {}).get("monthly") or []
        if not monthly:
            return None
        labels = [date.fromisoformat(m["month"] + "-01").strftime("%b %y") for m in monthly]
        totals = self.analysis["bank"]["totals"]
        neg_months = sum(1 for m in monthly if m["net"] < 0)
        take = (f"Net {fmt_value(totals['net'], 'INR')} over {totals['months']} months; "
                f"{neg_months} month(s) with net outflow")
        balance = [m["closing_balance"] if m["closing_balance"] is not None else float("nan") for m in monthly]
        return self._render("detailed_analysis", "Bank Cash Flows by Month", "bar", labels,
                            {"Inflows": [m["inflow"] for m in monthly], "Outflows": [-m["outflow"] for m in monthly]},
                            unit="INR", takeaway=take,
                            options={"colors": {"Inflows": "#16a34a", "Outflows": "#dc2626"}, "data_labels": False,
                                     "secondary": {"series": {"Closing balance": balance}, "unit": "INR", "data_labels": False}})

    def _counterparty_concentration(self):
        bank = self.analysis.get("bank") or {}
        rows = [("In: " + c["counterparty"], c["share"]) for c in bank.get("top_inflows", [])[:5]]
        rows += [("Out: " + c["counterparty"], c["share"]) for c in bank.get("top_outflows", [])[:5]]
        if not rows:
            return None
        top_in = bank["top_inflows"][0] if bank.get("top_inflows") else None
        take = (f"Largest payer '{top_in['counterparty']}' is {fmt_value(top_in['share'], '%')} of all inflows"
                if top_in else "")
        colors = ["#16a34a" if n.startswith("In:") else "#dc2626" for n, _ in rows]
        colors = ["#b45309" if n.startswith("In:") and s is not None and s >= 0.4 else c
                  for (n, s), c in zip(rows, colors)]
        return self._render("risk", "Counterparty Concentration (share of bank flows)", "hbar",
                            [n[:42] for n, _ in rows], {"Share": [s for _, s in rows]}, unit="%",
                            takeaway=take + " — amber = a single customer above 40% of inflows",
                            options={"hbar_colors": colors})

    # ---------------------------------------------------------------- captions

    def _caption_charts(self, charts: list[dict]) -> None:
        """One batch LLM call captions every chart at once (not one call per chart) --
        keeps delivery latency roughly flat no matter how many charts were rendered."""
        chart_context = [
            {"chart_id": c["chart_id"], "title": c["title"], "chart_type": c["spec"]["chart_type"],
             "unit": c["spec"].get("unit"), "computed_takeaway": c.get("takeaway"),
             "labels": c["spec"]["labels"], "series": c["spec"]["series"], "panels": c["spec"].get("panels")}
            for c in charts
        ]
        prompt = [
            {"role": "system", "content": prompts.CHART_EXPLAINER},
            {"role": "user", "content": embed_json("CHARTS_JSON", chart_context)},
        ]
        try:
            caption_set: ChartCaptionSet = self.call_llm(prompt, schema=ChartCaptionSet, tier="reasoning")
        except Exception:
            return  # captions are an enhancement, not load-bearing -- charts still render without them
        by_id = {c.chart_id: c.caption for c in caption_set.captions}
        for chart in charts:
            if chart["chart_id"] in by_id:
                chart["caption"] = by_id[chart["chart_id"]]


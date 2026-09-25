from __future__ import annotations

import json

from app.agents.base import AgentResult, ArtifactRef, Status, TaskSpec, WorkerAgent
from app.agents.schemas import ChartCaptionSet
from app.domain.facts import load_facts_by_period
from app.llm_gateway import prompts
from app.llm_gateway.prompt_utils import embed_json
from app.models.metric import Metric
from app.utils import storage
from app.utils.ids import new_id

# Chart selection is deterministic (design doc §2 principle 3: "deterministic first") --
# we already know exactly which metrics/accounts exist and their periods, so there's no
# ambiguity for an LLM to resolve here. The LLM's job (below) is only to WRITE the caption
# for each already-rendered chart, grounded in its actual data points.
_METRIC_GROUP_CHARTS = [
    ("Profitability Margins Trend", "line", ["gross_profit_pct", "ebitda_margin", "net_profit_margin"]),
    ("Liquidity Ratios Trend", "line", ["current_ratio", "quick_ratio", "cash_ratio"]),
    ("Leverage & Interest Coverage Trend", "line", ["debt_to_equity", "interest_coverage", "dscr"]),
    ("Cash Conversion Cycle (Days)", "line", ["dso", "dio", "dpo", "cash_conversion_cycle"]),
    ("Year-over-Year Growth", "bar", ["revenue_growth_yoy", "pat_growth_yoy"]),
    ("Return Ratios Trend", "line", ["roe", "roce", "asset_turnover"]),
]

# (chart title, [(series label, expense account_id), ...]) -- latest-period cost structure.
_COST_STRUCTURE_ACCOUNTS = [
    ("Cost of Materials", "PL.COGS"), ("Employee Costs", "PL.EMPLOYEE_COST"),
    ("Other Expenses", "PL.OTHER_EXPENSES"), ("Depreciation", "PL.DEPRECIATION"),
    ("Finance Costs", "PL.FINANCE_COST"),
]


class ChartSpecAgent(WorkerAgent):
    name = "chart_spec"
    allowed_tools = ["chart.render"]

    def execute(self, spec: TaskSpec) -> AgentResult:
        dataset_version_id = spec.params["dataset_version_id"]

        charts: list[dict] = []
        charts.extend(self._metric_group_charts(spec.job_id, dataset_version_id))
        forecast_chart = self._forecast_chart(spec.job_id, dataset_version_id)
        if forecast_chart:
            charts.append(forecast_chart)
        cost_chart = self._cost_structure_chart(spec.job_id, dataset_version_id)
        if cost_chart:
            charts.append(cost_chart)

        if charts:
            self._caption_charts(charts)

        uri = storage.write_text(f"{spec.job_id}/delivery/charts.json", json.dumps(charts))
        return AgentResult(
            task_id=spec.task_id, status=Status.DONE,
            outputs=[ArtifactRef(id="charts", kind="chart", uri=uri, row_count=len(charts))],
            summary=f"Rendered {len(charts)} chart(s).", confidence=0.85,
        )

    def _metric_group_charts(self, job_id: str, dataset_version_id: str) -> list[dict]:
        rendered = []
        for title, chart_type, metric_codes in _METRIC_GROUP_CHARTS:
            rows = (
                Metric.query.filter_by(dataset_version=dataset_version_id)
                .filter(Metric.metric_code.in_(metric_codes)).order_by(Metric.period_end).all()
            )
            if not rows:
                continue
            periods = sorted({r.period_end for r in rows})
            by_code = {code: {r.period_end: float(r.value) for r in rows if r.metric_code == code and r.value is not None}
                       for code in metric_codes}
            # matplotlib needs NaN, not None, for a gap in a line/bar series.
            series = {code: [by_code[code].get(p, float("nan")) for p in periods]
                      for code in metric_codes if by_code[code]}
            if not series:
                continue
            rendered.append(self._render(job_id, title, chart_type, [p.isoformat() for p in periods], series))
        return rendered

    def _forecast_chart(self, job_id: str, dataset_version_id: str) -> dict | None:
        # load_facts_by_period (not a raw FinancialFact query) so this shares the same
        # confidence-aware resolution as reconciliation/metrics -- a naive sum here
        # reintroduced the exact "several low-confidence rows pile into one named account"
        # bug fixed earlier for reconciliation, just for this one chart instead.
        facts_by_period = load_facts_by_period(dataset_version_id)
        forecast_rows = (
            Metric.query.filter_by(dataset_version=dataset_version_id)
            .filter(Metric.metric_code.in_(["revenue_forecast", "pat_forecast"])).all()
        )
        if not facts_by_period or not forecast_rows:
            return None

        actual = {"PL.REVENUE": {}, "PL.PAT": {}}
        for period, accounts in facts_by_period.items():
            for account_id in actual:
                if account_id in accounts:
                    actual[account_id][period] = accounts[account_id]
        forecast = {"revenue_forecast": {}, "pat_forecast": {}}
        for m in forecast_rows:
            if m.value is not None:
                forecast[m.metric_code][m.period_end] = float(m.value)

        pairs = [("PL.REVENUE", "revenue_forecast", "Revenue"), ("PL.PAT", "pat_forecast", "PAT")]
        all_periods = sorted({p for d in list(actual.values()) + list(forecast.values()) for p in d})
        if not all_periods:
            return None

        series: dict[str, list[float]] = {}
        for actual_key, forecast_key, label in pairs:
            actual_map, forecast_map = actual.get(actual_key, {}), forecast.get(forecast_key, {})
            if not actual_map and not forecast_map:
                continue
            last_actual_period = max(actual_map.keys()) if actual_map else None
            actual_series, forecast_series = [], []
            for p in all_periods:
                actual_series.append(actual_map.get(p, float("nan")))
                if p in forecast_map:
                    forecast_series.append(forecast_map[p])
                elif p == last_actual_period:
                    forecast_series.append(actual_map.get(p, float("nan")))  # bridges the two lines visually
                else:
                    forecast_series.append(float("nan"))
            series[f"{label} (Actual)"] = actual_series
            series[f"{label} (Forecast)"] = forecast_series

        if not series:
            return None
        return self._render(job_id, "Revenue & PAT: Actual vs. Forecast", "line",
                             [p.isoformat() for p in all_periods], series)

    def _cost_structure_chart(self, job_id: str, dataset_version_id: str) -> dict | None:
        facts_by_period = load_facts_by_period(dataset_version_id)
        if not facts_by_period:
            return None
        latest_period = max(facts_by_period.keys())
        totals = facts_by_period[latest_period]
        labels, values = [], []
        for label, account_id in _COST_STRUCTURE_ACCOUNTS:
            v = totals.get(account_id)
            if v and v > 0:
                labels.append(label)
                values.append(v)
        if not values:
            return None
        title = f"Cost Structure — {latest_period.isoformat()}"
        return self._render(job_id, title, "pie", labels, {title: values})

    def _render(self, job_id: str, title: str, chart_type: str, labels: list[str], series: dict) -> dict:
        chart_id = new_id("chart_")
        rendered = self.call_tool(
            "chart.render", job_id=job_id, chart_id=chart_id, title=title,
            chart_type=chart_type, labels=labels, series=series,
        )
        return {"chart_id": chart_id, "title": title, "caption": "", **rendered}

    def _caption_charts(self, charts: list[dict]) -> None:
        """One batch LLM call captions every chart at once (not one call per chart) --
        keeps the delivery stage's latency roughly flat no matter how many charts got
        rendered, which matters given the whole pipeline is expected to finish in ~2
        minutes end to end."""
        chart_context = [
            {"chart_id": c["chart_id"], "title": c["title"], "chart_type": c["spec"]["chart_type"],
             "labels": c["spec"]["labels"], "series": c["spec"]["series"]}
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

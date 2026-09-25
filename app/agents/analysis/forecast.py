from __future__ import annotations

from app.agents.analysis.common import findings_prompt
from app.agents.base import AgentResult, ArtifactRef, Status, TaskSpec, WorkerAgent
from app.agents.schemas import FindingsSet
from app.domain.facts import load_facts_by_period
from app.extensions import db
from app.models.finding import Finding
from app.tools.calc.metrics import persist_metrics

_FORECAST_ACCOUNTS = {"PL.REVENUE": "revenue_forecast", "PL.PAT": "pat_forecast"}


class ForecastAgent(WorkerAgent):
    name = "forecast"
    allowed_tools = ["forecast.run", "sql.query_readonly"]

    def execute(self, spec: TaskSpec) -> AgentResult:
        dataset_version_id = spec.params["dataset_version_id"]
        facts_by_period = load_facts_by_period(dataset_version_id)
        periods_sorted = sorted(facts_by_period.keys())

        if len(periods_sorted) < 2:
            return AgentResult(
                task_id=spec.task_id, status=Status.PARTIAL,
                summary="Not enough periods of history to forecast (need at least 2).", confidence=0.3,
            )

        step = periods_sorted[-1] - periods_sorted[-2]
        forecast_metric_dicts = []
        for account_id, metric_code in _FORECAST_ACCOUNTS.items():
            series = [facts_by_period[p][account_id] for p in periods_sorted if account_id in facts_by_period[p]]
            if len(series) < 2:
                continue
            result = self.call_tool("forecast.run", series=series, periods_ahead=2)
            for i, value in enumerate(result["forecast"]):
                future_period = periods_sorted[-1] + (step * (i + 1))
                forecast_metric_dicts.append({
                    "metric_code": metric_code, "period_end": future_period, "value": value,
                    "unit": "INR", "formula_version": result["method"], "inputs": [account_id],
                })

        if not forecast_metric_dicts:
            return AgentResult(
                task_id=spec.task_id, status=Status.PARTIAL,
                summary="No forecastable series found (revenue/PAT history missing).", confidence=0.3,
            )

        saved = persist_metrics(dataset_version_id, forecast_metric_dicts)

        prompt = findings_prompt(saved, spec.params.get("user_guidance"))
        findings_set: FindingsSet = self.call_llm(prompt, schema=FindingsSet, tier="reasoning")
        for item in findings_set.findings:
            db.session.add(Finding(
                dataset_version=dataset_version_id, module="forecast", severity=item.severity,
                title=item.title, body=item.body, metric_ids=item.metric_ids, confidence=0.7,
            ))
        db.session.commit()

        return AgentResult(
            task_id=spec.task_id, status=Status.DONE,
            outputs=[ArtifactRef(id=dataset_version_id, kind="metric_set", uri="db://metrics", row_count=len(saved))],
            summary=f"Forecasted {len(saved)} future metric points.", confidence=0.7,
        )

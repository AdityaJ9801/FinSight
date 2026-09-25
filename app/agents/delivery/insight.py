from __future__ import annotations

import json

from flask import current_app

from app.agents.base import AgentResult, ArtifactRef, Status, TaskSpec, WorkerAgent
from app.agents.schemas import InsightSet
from app.domain.facts import load_facts_by_period
from app.llm_gateway import prompts
from app.llm_gateway.prompt_utils import embed_json
from app.models.dataset import DatasetVersion
from app.models.finding import Finding
from app.models.metric import Metric
from app.models.tenant import Entity
from app.tools.calc.health_score import compute_health_score
from app.tools.calc.metrics import persist_metrics
from app.tools.web_search import WebSearchError
from app.utils import storage


class InsightReasonerAgent(WorkerAgent):
    name = "insight_reasoner"
    allowed_tools = ["metrics.compute", "health_score.compute", "web.search"]

    def execute(self, spec: TaskSpec) -> AgentResult:
        dataset_version_id = spec.params["dataset_version_id"]

        # "Latest period" for the health score must come from the actual source facts, not
        # from the metrics table's max period_end -- forecast metrics (analysis/forecast.py)
        # are written against synthetic future dates and would otherwise look "latest".
        facts_by_period = load_facts_by_period(dataset_version_id)
        latest_metrics: dict[str, float] = {}
        if facts_by_period:
            latest_actual_period = max(facts_by_period.keys())
            rows = Metric.query.filter_by(dataset_version=dataset_version_id, period_end=latest_actual_period).all()
            latest_metrics = {m.metric_code: float(m.value) for m in rows if m.value is not None}

        health = self.call_tool("health_score.compute", latest_metrics=latest_metrics) if latest_metrics else None
        if health is not None:
            # Persisted as a real metric (not just left in the insights.json payload) so
            # {{m:health_score:period_end}} is an actually-resolvable placeholder -- without
            # this, the report/verifier's ONLY way to cite an exact score is a placeholder
            # that can never resolve, since nothing backs it in the metrics table (confirmed
            # live: the writer cited {{m:health_score:...}} and the verifier correctly
            # rejected it as unresolvable).
            persist_metrics(dataset_version_id, [{
                "metric_code": "health_score", "period_end": latest_actual_period, "value": health["score"],
                "unit": "pts", "formula_version": "1.0", "inputs": list(latest_metrics.keys()),
            }])

        benchmark_context = self._industry_benchmark_search(dataset_version_id)

        findings = Finding.query.filter_by(dataset_version=dataset_version_id).all()
        all_metrics = Metric.query.filter_by(dataset_version=dataset_version_id).all()
        metrics_ctx = [{
            "id": m.id, "metric_code": m.metric_code, "period_end": m.period_end.isoformat(),
            "value": float(m.value) if m.value is not None else None, "unit": m.unit,
        } for m in all_metrics]
        findings_ctx = [{
            "module": f.module, "title": f.title, "body": f.body, "severity": f.severity,
            "metric_ids": f.metric_ids,
        } for f in findings]

        user_content = (
            embed_json("METRICS_JSON", metrics_ctx) + "\n" + embed_json("FINDINGS_JSON", findings_ctx) + "\n"
            + embed_json("HEALTH_SCORE_JSON", health) + "\n" + embed_json("BENCHMARK_CONTEXT_JSON", benchmark_context)
        )
        user_guidance = spec.params.get("user_guidance")
        if user_guidance:
            user_content += "\n" + embed_json("USER_GUIDANCE_JSON", user_guidance)
        prompt = [
            {"role": "system", "content": prompts.INSIGHT_REASONER},
            {"role": "user", "content": user_content},
        ]
        insight_set: InsightSet = self.call_llm(prompt, schema=InsightSet, tier="reasoning")

        # findings/metrics/benchmark are already loaded above for the insight-reasoning
        # prompt -- persisted alongside the ranked insights too, so the report writer can
        # draw on the full detail (not just the top-line insights) without another LLM call
        # or another DB round-trip.
        payload = {
            "insights": [i.model_dump() for i in insight_set.insights], "health_score": health,
            "findings": findings_ctx, "metrics": metrics_ctx, "benchmark_context": benchmark_context,
        }
        uri = storage.write_text(f"{spec.job_id}/delivery/insights.json", json.dumps(payload))

        return AgentResult(
            task_id=spec.task_id, status=Status.DONE,
            outputs=[ArtifactRef(id="insights", kind="text", uri=uri, row_count=len(insight_set.insights))],
            summary=f"Generated {len(insight_set.insights)} insights"
                    + (f"; health score {health['score']} ({health['rating']})" if health else ""),
            confidence=0.8,
        )

    def _industry_benchmark_search(self, dataset_version_id: str) -> list[dict]:
        """Best-effort industry-benchmark lookup via the web search tool. Never blocks or
        fails the job -- a search-engine hiccup shouldn't take down report generation."""
        if not current_app.config.get("WEB_SEARCH_ENABLED"):
            return []
        dataset_version = DatasetVersion.query.get(dataset_version_id)
        entity = Entity.query.get(dataset_version.entity_id) if dataset_version and dataset_version.entity_id else None
        industry = entity.industry if entity else None
        if not industry:
            return []
        try:
            return self.call_tool(
                "web.search", query=f"{industry} industry average financial ratios India benchmark",
                num_results=current_app.config["WEB_SEARCH_NUM_RESULTS"],
                lines_per_result=current_app.config["WEB_SEARCH_LINES_PER_RESULT"],
                timeout_s=current_app.config["WEB_SEARCH_TIMEOUT_S"],
            )
        except WebSearchError:
            return []

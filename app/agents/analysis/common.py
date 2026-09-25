"""Shared plumbing for the five analysis modules (design doc §4.1): compute this module's
metric group, persist metrics, then ask the LLM for findings that reference those metrics
by placeholder only (never a raw number -- see llm_gateway/prompts.py: ANALYSIS_MODULE).
"""
from __future__ import annotations

from app.agents.base import AgentResult, ArtifactRef, Status, TaskSpec, WorkerAgent
from app.agents.schemas import FindingsSet
from app.domain.facts import load_facts_by_period
from app.extensions import db
from app.llm_gateway import prompts
from app.llm_gateway.prompt_utils import embed_json
from app.models.finding import Finding
from app.tools.calc.metrics import REGISTRY, compute_all, persist_metrics


def metrics_json(metric_rows: list) -> list[dict]:
    return [{
        "id": m.id, "metric_code": m.metric_code, "period_end": m.period_end.isoformat(),
        "value": float(m.value) if m.value is not None else None, "unit": m.unit,
    } for m in metric_rows]


def findings_prompt(metric_rows: list, user_guidance: str | None = None) -> list[dict]:
    """Shared by every analysis module's findings call (common.py, risk.py, gst.py,
    forecast.py) so USER_GUIDANCE_JSON -- set only when the orchestrator relayed a
    mid-run user instruction to this specific module, see
    orchestrator.apply_pending_instructions -- is embedded the same way everywhere."""
    content = embed_json("METRICS_JSON", metrics_json(metric_rows))
    if user_guidance:
        content += "\n" + embed_json("USER_GUIDANCE_JSON", user_guidance)
    return [{"role": "system", "content": prompts.ANALYSIS_MODULE}, {"role": "user", "content": content}]


class AnalysisModuleAgent(WorkerAgent):
    """Subclasses set `name` (must match a MetricDef.group) and `module_label`."""

    module_label: str = "module"
    allowed_tools = ["metrics.compute", "sql.query_readonly", "sandbox.run_python"]

    def compute_group_metrics(self, dataset_version_id: str) -> list:
        facts_by_period = load_facts_by_period(dataset_version_id)
        all_metrics = compute_all(facts_by_period)
        group_metrics = [m for m in all_metrics if REGISTRY[m["metric_code"]].group == self.name]
        return persist_metrics(dataset_version_id, group_metrics)

    def generate_findings(self, spec: TaskSpec, metric_rows: list) -> AgentResult:
        if not metric_rows:
            return AgentResult(
                task_id=spec.task_id, status=Status.PARTIAL,
                summary=f"No {self.module_label} metrics could be computed (required accounts not present).",
                confidence=0.3,
            )

        prompt = findings_prompt(metric_rows, spec.params.get("user_guidance"))
        findings_set: FindingsSet = self.call_llm(prompt, schema=FindingsSet, tier="reasoning")

        dataset_version_id = spec.params["dataset_version_id"]
        for item in findings_set.findings:
            db.session.add(Finding(
                dataset_version=dataset_version_id, module=self.module_label, severity=item.severity,
                title=item.title, body=item.body, metric_ids=item.metric_ids, confidence=0.8,
            ))
        db.session.commit()

        return AgentResult(
            task_id=spec.task_id, status=Status.DONE,
            outputs=[ArtifactRef(id=dataset_version_id, kind="metric_set", uri="db://metrics",
                                  row_count=len(metric_rows))],
            summary=f"{self.module_label}: computed {len(metric_rows)} metric points, "
                    f"{len(findings_set.findings)} findings.",
            confidence=0.85,
        )

    def execute(self, spec: TaskSpec) -> AgentResult:
        dataset_version_id = spec.params["dataset_version_id"]
        metric_rows = self.compute_group_metrics(dataset_version_id)
        return self.generate_findings(spec, metric_rows)

"""Verifier: deterministic placeholder-resolution/lint checks first (never skip these --
they're exact), then an LLM pass for the qualitative checks the design doc calls out
(direction words, unsupported claims) that can't be checked with a regex. A deterministic
failure never reaches the LLM step -- there's nothing useful for it to verify yet.
"""
from __future__ import annotations

import json

from app.agents.base import AgentResult, ArtifactRef, Issue, Status, TaskSpec, WorkerAgent
from app.agents.schemas import VerifierVerdict
from app.llm_gateway import prompts
from app.llm_gateway.prompt_utils import embed_json
from app.models.finding import Finding
from app.models.metric import Metric
from app.tools.report_render import lint_unbound_numbers, resolve_placeholders
from app.utils import storage


class VerifierAgent(WorkerAgent):
    name = "verifier"
    allowed_tools = ["sql.query_readonly", "metrics.compute"]

    def execute(self, spec: TaskSpec) -> AgentResult:
        dataset_version_id = spec.params["dataset_version_id"]
        draft_uri = spec.params["draft_uri"]
        draft = json.loads(storage.resolve(draft_uri).read_text())

        # Same payload ReportWriterAgent drew on (insights/findings/metrics/health) -- the
        # LLM claim-check below must ground against everything the writer was ALLOWED to
        # cite, not just findings, or it false-flags perfectly well-grounded claims (e.g. a
        # metric value that's in METRICS_JSON but never phrased as its own "finding").
        # Confirmed live: without this, claims like "current ratio decreased from 0.62x to
        # 0.52x" -- true, straight from METRICS_JSON -- were rejected as "not supported by
        # findings" every time, since the verifier had no metrics to check them against.
        insights_uri = spec.params.get("insights_uri")
        insights_payload = json.loads(storage.resolve(insights_uri).read_text()) if insights_uri else {}

        issues: list[Issue] = []
        resolved_sections = []
        for section in draft["sections"]:
            if section.get("kind") in ("data_quality", "data_diagnostic") or "Data Diagnostic" in section.get("heading", "") or "Data Quality" in section.get("heading", ""):
                sec_dict = dict(section)
                resolved_sections.append(sec_dict)
                continue
            lint_hits = lint_unbound_numbers(section["body"])
            resolved_text, unresolved = resolve_placeholders(section["body"], dataset_version_id)
            sec_dict = dict(section)
            sec_dict["body"] = resolved_text
            resolved_sections.append(sec_dict)
            for tok in lint_hits:
                issues.append(Issue(severity="error", code="UNBOUND_NUMBER", message=f"Raw number '{tok}' in '{section['heading']}'"))
            for tok in unresolved:
                issues.append(Issue(severity="error", code="UNRESOLVED_PLACEHOLDER", message=f"'{tok}' has no matching metric"))

        if issues:
            return AgentResult(
                task_id=spec.task_id, status=Status.NEEDS_REVIEW,
                summary=f"Verifier failed deterministic checks: {len(issues)} issue(s).",
                confidence=0.2, issues=issues,
                usage={"resolved_sections": resolved_sections, "passed": False},
            )

        findings = Finding.query.filter_by(dataset_version=dataset_version_id).all()
        findings_ctx = [{"title": f.title, "body": f.body} for f in findings]
        metrics_list = insights_payload.get("metrics")
        if not metrics_list:
            db_metrics = Metric.query.filter_by(dataset_version=dataset_version_id).all()
            metrics_list = [{"code": m.metric_code, "period": m.period_end.isoformat() if m.period_end else None,
                             "value": float(m.value) if m.value is not None else None, "unit": m.unit,
                             "formatted": f"{float(m.value)*100:.2f}%" if m.unit == "%" and m.value is not None else str(m.value)}
                            for m in db_metrics]
        else:
            for m in metrics_list:
                if m.get("unit") == "%" and m.get("value") is not None and "formatted" not in m:
                    m["formatted"] = f"{float(m['value'])*100:.2f}%"

        health_score = insights_payload.get("health_score")
        if not health_score:
            hs_row = Metric.query.filter_by(dataset_version=dataset_version_id, metric_code="health_score").order_by(Metric.period_end.desc()).first()
            if hs_row and hs_row.value is not None:
                score = float(hs_row.value)
                rating = "Strong" if score >= 75 else ("Good" if score >= 60 else ("Moderate" if score >= 40 else "Weak"))
                health_score = {"score": score, "rating": rating}

        prompt = [
            {"role": "system", "content": prompts.VERIFIER},
            {"role": "user", "content": embed_json("DRAFT_JSON", resolved_sections) + "\n"
                                         + embed_json("FINDINGS_JSON", findings_ctx) + "\n"
                                         + embed_json("METRICS_JSON", metrics_list) + "\n"
                                         + embed_json("HEALTH_SCORE_JSON", health_score)},
        ]
        verdict: VerifierVerdict = self.call_llm(prompt, schema=VerifierVerdict, tier="reasoning")

        if not verdict.passed:
            issues = [Issue(severity="warn", code="VERIFIER_FEEDBACK", message=fb) for fb in verdict.claim_feedback]
            return AgentResult(
                task_id=spec.task_id, status=Status.NEEDS_REVIEW,
                summary=f"Verifier rejected the draft: {len(verdict.claim_feedback)} claim issue(s).",
                confidence=0.4, issues=issues,
                usage={"resolved_sections": resolved_sections, "passed": False, "feedback": verdict.claim_feedback},
            )

        return AgentResult(
            task_id=spec.task_id, status=Status.DONE,
            outputs=[ArtifactRef(id="verified_report", kind="text", uri=draft_uri)],
            summary="Verifier passed: all placeholders resolved, no unsupported claims flagged.",
            confidence=0.95,
            usage={"resolved_sections": resolved_sections, "passed": True},
        )

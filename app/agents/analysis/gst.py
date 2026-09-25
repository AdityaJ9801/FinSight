from __future__ import annotations

from collections import defaultdict

from app.agents.base import AgentResult, ArtifactRef, Status, TaskSpec, WorkerAgent
from app.agents.schemas import FindingsSet
from app.domain.facts import load_facts_by_period
from app.extensions import db
from app.llm_gateway import prompts
from app.llm_gateway.prompt_utils import embed_json
from app.models.finding import Finding
from app.models.gst import GstReturn
from app.tools.calc.metrics import persist_metrics

GST_TIE_TOLERANCE_PCT = 0.05  # configurable per design doc §6.5 ("configurable %")


def _sum_matching(rows: list[GstReturn], keywords: list[str]) -> float:
    return sum(float(r.value) for r in rows if any(k in r.field.lower() for k in keywords))


class GstComplianceAgent(WorkerAgent):
    name = "gst"
    allowed_tools = ["sql.query_readonly", "recon.run_checks", "web.search"]

    def execute(self, spec: TaskSpec) -> AgentResult:
        dataset_version_id = spec.params["dataset_version_id"]
        gst_rows = GstReturn.query.filter_by(dataset_version=dataset_version_id).all()

        if not gst_rows:
            return AgentResult(task_id=spec.task_id, status=Status.PARTIAL,
                                summary="No GST returns uploaded for this job; skipping GST reconciliation.",
                                confidence=0.3)

        by_period_type: dict = defaultdict(list)
        for r in gst_rows:
            by_period_type[(r.period, r.return_type)].append(r)

        facts_by_period = load_facts_by_period(dataset_version_id)
        metric_dicts = []
        findings_context = []

        for (period, _), _rows in list(by_period_type.items()):
            gstr3b = by_period_type.get((period, "GSTR3B"), [])
            gstr2b = by_period_type.get((period, "GSTR2B"), [])

            if gstr3b:
                taxable_outward = _sum_matching(gstr3b, ["taxable", "outward"])
                books_revenue = facts_by_period.get(period, {}).get("PL.REVENUE")
                if books_revenue:
                    mismatch_pct = abs(taxable_outward - books_revenue) / books_revenue
                    metric_dicts.append({
                        "metric_code": "gst_sales_tie_mismatch_pct", "period_end": period, "value": mismatch_pct,
                        "unit": "%", "formula_version": "1.0", "inputs": ["GSTR3B.taxable_outward", "PL.REVENUE"],
                    })
                    findings_context.append({
                        "check": "GST_SALES_TIE", "period": period.isoformat(), "mismatch_pct": mismatch_pct,
                        "within_tolerance": mismatch_pct <= GST_TIE_TOLERANCE_PCT,
                    })

            if gstr3b and gstr2b:
                itc_claimed = _sum_matching(gstr3b, ["itc"])
                itc_available = _sum_matching(gstr2b, ["itc", "eligible"])
                if itc_available:
                    mismatch_pct = abs(itc_claimed - itc_available) / itc_available
                    metric_dicts.append({
                        "metric_code": "gst_itc_tie_mismatch_pct", "period_end": period, "value": mismatch_pct,
                        "unit": "%", "formula_version": "1.0", "inputs": ["GSTR3B.itc", "GSTR2B.itc"],
                    })
                    findings_context.append({
                        "check": "GST_ITC_TIE", "period": period.isoformat(), "mismatch_pct": mismatch_pct,
                        "within_tolerance": mismatch_pct <= GST_TIE_TOLERANCE_PCT,
                    })

        if not metric_dicts:
            return AgentResult(task_id=spec.task_id, status=Status.PARTIAL,
                                summary="GST returns present but no matching books revenue for the same period(s).",
                                confidence=0.4)

        saved = persist_metrics(dataset_version_id, metric_dicts)

        user_content = (embed_json("METRICS_JSON", [
                {"id": m.id, "metric_code": m.metric_code, "period_end": m.period_end.isoformat(),
                 "value": float(m.value), "unit": m.unit} for m in saved
            ]) + "\n" + embed_json("GST_CONTEXT_JSON", findings_context))
        user_guidance = spec.params.get("user_guidance")
        if user_guidance:
            user_content += "\n" + embed_json("USER_GUIDANCE_JSON", user_guidance)
        prompt = [
            {"role": "system", "content": prompts.ANALYSIS_MODULE},
            {"role": "user", "content": user_content},
        ]
        findings_set: FindingsSet = self.call_llm(prompt, schema=FindingsSet, tier="reasoning")
        for item in findings_set.findings:
            db.session.add(Finding(
                dataset_version=dataset_version_id, module="gst_compliance", severity=item.severity,
                title=item.title, body=item.body, metric_ids=item.metric_ids, confidence=0.8,
            ))
        db.session.commit()

        return AgentResult(
            task_id=spec.task_id, status=Status.DONE,
            outputs=[ArtifactRef(id=dataset_version_id, kind="metric_set", uri="db://metrics", row_count=len(saved))],
            summary=f"GST reconciliation computed {len(saved)} tie-out metric(s).", confidence=0.8,
        )

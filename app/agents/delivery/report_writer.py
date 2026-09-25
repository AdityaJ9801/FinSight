from __future__ import annotations

import json

from app.agents.base import AgentResult, ArtifactRef, Issue, Status, TaskSpec, WorkerAgent
from app.agents.schemas import ReportDraftResult, ReportSection
from app.domain.taxonomy import build_report_skeleton
from app.domain.validation_rules import within_materiality
from app.llm_gateway import prompts
from app.llm_gateway.prompt_utils import embed_json
from app.models.review import ReviewItem
from app.tools.report_render import lint_unbound_numbers
from app.utils import storage


class ReportWriterAgent(WorkerAgent):
    name = "report_writer"
    allowed_tools = ["report.render"]

    def execute(self, spec: TaskSpec) -> AgentResult:
        insights_uri = spec.params["insights_uri"]
        payload = json.loads(storage.resolve(insights_uri).read_text())
        insights = payload.get("insights", [])

        # Load rendered charts if chart_spec has already run
        charts: list[dict] = []
        charts_path = f"{spec.job_id}/delivery/charts.json"
        if storage.resolve(charts_path).exists():
            try:
                charts = json.loads(storage.resolve(charts_path).read_text())
            except Exception:
                charts = []

        # Deterministic skeleton planning: anchor sections and required topics in data
        skeleton = build_report_skeleton(
            metrics=payload.get("metrics", []),
            findings=payload.get("findings", []),
            health_score=payload.get("health_score"),
            charts=charts,
        )

        user_content = (
            embed_json("SKELETON_JSON", skeleton) + "\n"
            + embed_json("INSIGHTS_JSON", insights) + "\n"
            + embed_json("FINDINGS_JSON", payload.get("findings", [])) + "\n"
            + embed_json("METRICS_JSON", payload.get("metrics", [])) + "\n"
            + embed_json("HEALTH_SCORE_JSON", payload.get("health_score"))
        )
        if charts:
            chart_summaries = [
                {"chart_id": c.get("chart_id"), "title": c.get("title"), "caption": c.get("caption", "")}
                for c in charts
            ]
            user_content += "\n" + embed_json("CHARTS_JSON", chart_summaries)

        user_guidance = spec.params.get("user_guidance")
        if user_guidance:
            user_content += "\n" + embed_json("USER_GUIDANCE_JSON", user_guidance)

        # A prior draft failed the verifier's claim-check -- feed specific feedback back in
        verifier_feedback = spec.params.get("verifier_feedback")
        if verifier_feedback:
            user_content += "\n" + embed_json("PRIOR_DRAFT_REJECTED_BECAUSE_JSON", verifier_feedback) + (
                "\nRewrite the draft addressing each point above -- either correct the claim to "
                "match the data, or remove it if it can't be made accurate."
            )

        base_prompt = [
            {"role": "system", "content": prompts.REPORT_WRITER},
            {"role": "user", "content": user_content},
        ]
        draft: ReportDraftResult = self.call_llm(base_prompt, schema=ReportDraftResult, tier="reasoning")

        # Ensure skeleton alignment: populate section_key and chart_ids if omitted by model
        skeleton_by_idx = {i: sk for i, sk in enumerate(skeleton)}
        skeleton_by_key = {sk["section_key"]: sk for sk in skeleton}
        for idx, sec in enumerate(draft.sections):
            if not sec.section_key:
                matched_sk = skeleton_by_idx.get(idx) or skeleton_by_key.get(sec.heading.lower().replace(" ", "_"))
                if matched_sk:
                    sec.section_key = matched_sk["section_key"]
                    if not sec.chart_ids:
                        sec.chart_ids = matched_sk.get("chart_ids", [])
            elif sec.section_key in skeleton_by_key and not sec.chart_ids:
                sec.chart_ids = skeleton_by_key[sec.section_key].get("chart_ids", [])

        lint_issues: list[str] = []
        for section in draft.sections:
            lint_issues.extend(lint_unbound_numbers(section.body))

        if lint_issues:
            retry_prompt = base_prompt + [
                {"role": "assistant", "content": json.dumps(draft.model_dump())},
                {"role": "user", "content": f"These raw numbers must be replaced with {{{{m:code:period}}}} "
                                             f"placeholders instead: {lint_issues}. Rewrite the full draft."},
            ]
            draft = self.call_llm(retry_prompt, schema=ReportDraftResult, tier="reasoning")
            lint_issues = []
            for section in draft.sections:
                lint_issues.extend(lint_unbound_numbers(section.body))

        draft_dict = draft.model_dump()
        dq = self._data_quality_section(spec.job_id)
        if dq:
            dq["section_key"] = "data_quality"
            dq["kind"] = "data_quality"
            dq["chart_ids"] = []
        draft_dict["data_quality_section"] = dq
        draft_dict["skeleton"] = skeleton

        uri = storage.write_text(f"{spec.job_id}/delivery/draft.json", json.dumps(draft_dict))
        issues = [Issue(severity="warn", code="UNBOUND_NUMBER", message=tok) for tok in lint_issues]

        return AgentResult(
            task_id=spec.task_id, status=Status.DONE if not lint_issues else Status.PARTIAL,
            outputs=[ArtifactRef(id="draft", kind="text", uri=uri)],
            summary=f"Drafted report '{draft.title}' with {len(draft.sections)} section(s)"
                    + (f", {len(lint_issues)} unresolved raw number(s)" if lint_issues else ""),
            confidence=0.9 if not lint_issues else 0.5,
            issues=issues,
        )

    @staticmethod
    def _data_quality_section(job_id: str) -> dict | None:
        """Plain-language Data Quality & Methodology paragraph built directly from a DB
        query -- real counts of how much of the dataset was auto-approved at low confidence
        vs needed human review (see DataSupervisor.run_stage's blocking-vs-gap split and
        RECONCILIATION_MATERIALITY_PCT). Re-evaluates materiality against each open
        reconciliation item's own payload rather than trusting a persisted flag, since
        auto-approval isn't recorded as a separate status on the item (see
        within_materiality's docstring). Returns None when there's nothing to report."""
        from flask import current_app

        materiality_pct = current_app.config.get("RECONCILIATION_MATERIALITY_PCT", 0.15)
        items = ReviewItem.query.filter_by(job_id=job_id).all()
        if not items:
            return None
        mapping_items = [i for i in items if i.kind == "mapping"]
        recon_items = [i for i in items if i.kind == "reconciliation"]
        open_recon = [i for i in recon_items if i.status == "open"]

        auto_mapped = sum(1 for i in mapping_items if i.status != "resolved")
        analyst_mapped = sum(1 for i in mapping_items if i.status == "resolved")
        auto_recon = sum(1 for i in open_recon if within_materiality(i.payload, materiality_pct))
        analyst_recon = sum(1 for i in recon_items if i.status == "resolved")

        sentences = []
        if auto_mapped:
            sentences.append(
                f"{auto_mapped} account-mapping guess(es) were made at low confidence and "
                f"auto-approved rather than blocking the pipeline (AUTO_APPROVE_LOW_CONFIDENCE); "
                f"figures resting on these carry more uncertainty than clearly-labeled line items."
            )
        if analyst_mapped:
            sentences.append(f"{analyst_mapped} mapping(s) were corrected by an analyst before this report was generated.")
        if auto_recon:
            sentences.append(
                f"{auto_recon} reconciliation check(s) (e.g. recomputed vs. stated subtotals) fell "
                f"outside exact tolerance but within {materiality_pct:.0%} of the expected value, and "
                f"were accepted as a gap rather than blocked -- commonly because the chart of accounts "
                f"used is a documented Schedule III subset that doesn't have a named line for every "
                f"possible caption (e.g. minority interest, share of associates' profit)."
            )
        if analyst_recon:
            sentences.append(f"{analyst_recon} reconciliation item(s) were reviewed and accepted by an analyst.")
        if not sentences:
            sentences.append("No mapping or reconciliation gaps were flagged for this dataset.")

        return {"heading": "Data Quality & Methodology Notes", "body": " ".join(sentences)}

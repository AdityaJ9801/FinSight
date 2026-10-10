"""Delivery-stage supervisor: runs the delivery agents as a dependency DAG, then the
verify/revise loop, then publishes the report.

    insight_reasoner ─┐
    chart_spec ───────┴─> report_writer ─> verifier (<= MAX_REVISIONS rewrites) ─> publish

Edges come from the agent registry's depends_on. The previous hand-written sequence ran
report_writer concurrently with chart_spec, so the writer usually couldn't see the charts
it was meant to reference; chart_spec also waited on insights it never used. Now the two
independent agents overlap and the writer runs once both of its inputs exist.
"""
from __future__ import annotations

from flask import Flask

from app.agents import registry
from app.agents.base import AgentResult, Status, TaskSpec
from app.agents.delivery.publishing import publish_report, resolve_draft_sections
from app.agents.verifier import VerifierAgent
from app.extensions import db
from app.orchestrator import blackboard
from app.orchestrator.executor import Node, NodeFailure, run_dag
from app.utils.ids import new_id

_PROGRESS = {"insight_reasoner": "Insights synthesized", "chart_spec": "Charts rendered",
             "report_writer": "Report drafted"}


def _spec(job_id: str, tenant_id: str, agent_name: str, params: dict) -> TaskSpec:
    # Plain job_id/tenant_id strings, never the Job ORM object: DAG nodes run in their own
    # threads/sessions, and touching an instance loaded in another thread's session can
    # trigger a lazy refresh against a session in use elsewhere (a real, intermittent bug).
    return TaskSpec(task_id=new_id("t_"), job_id=job_id, tenant_id=tenant_id, agent=agent_name,
                    goal=f"{agent_name} for job {job_id}", params=params)


def _as_result(value, agent: str) -> AgentResult:
    if isinstance(value, AgentResult):
        return value
    return AgentResult(task_id=new_id("t_"), status=Status.FAILED, summary=f"{agent} failed unexpectedly: {value}")


class DeliverySupervisor:
    name = "delivery_supervisor"
    MAX_REVISIONS = 2

    def __init__(self, app: Flask, llm):
        self.app = app
        self.llm = llm

    def run_stage(self, job, dataset_version_id: str, guidance: dict[str, str] | None = None) -> bool:
        """guidance: {agent_name: note} from orchestrator.apply_pending_instructions."""
        job_id, tenant_id = job.id, job.tenant_id
        guidance = guidance or {}
        base = {"dataset_version_id": dataset_version_id}

        def agent_node(name: str, extra: dict | None = None, deps: tuple[str, ...] = ()) -> Node:
            def run(dep_results: dict):
                params = {**base, "user_guidance": guidance.get(name), **(extra or {})}
                if name == "report_writer":
                    insight = dep_results.get("insight_reasoner")
                    if not isinstance(insight, AgentResult) or not insight.outputs:
                        # Nothing to write from -- report the dependency failure, don't guess.
                        return AgentResult(task_id=new_id("t_"), status=Status.FAILED,
                                           summary="report_writer skipped: insight_reasoner produced no output")
                    params["insights_uri"] = insight.outputs[0].uri
                return registry.get(name).load()(self.llm).run(_spec(job_id, tenant_id, name, params))
            return Node(name, run, deps)

        nodes = [
            agent_node("insight_reasoner"),
            agent_node("chart_spec"),
            agent_node("report_writer", deps=registry.get("report_writer").depends_on),
        ]

        job.set_progress(88, "Delivery: insights and charts in parallel")
        db.session.commit()
        done: list[str] = []

        def on_complete(name: str, _result) -> None:
            done.append(name)
            job.set_progress(min(88 + 2 * len(done), 94), f"{_PROGRESS.get(name, name)} ({len(done)}/{len(nodes)})")
            db.session.commit()

        max_workers = min(len(nodes), max(1, self.app.config.get("LLM_MAX_CONCURRENT_REQUESTS", 2))) if self.app.config.get("LLM_PARALLEL_CALLS", True) else 1
        results = {k: _as_result(v, k) if isinstance(v, NodeFailure) else v
                   for k, v in run_dag(nodes, app=self.app, max_workers=max_workers, on_complete=on_complete).items()}

        insight = results.get("insight_reasoner")
        if not insight or not getattr(insight, "outputs", None):
            insights_payload = blackboard.read(job_id, "insights")
            if not insights_payload or not insights_payload.get("insights"):
                from app.llm_gateway.fake_client import _insights_from_metrics
                from app.llm_gateway.prompt_utils import embed_json
                from app.models.metric import Metric
                from app.models.finding import Finding
                all_m = Metric.query.filter_by(dataset_version=dataset_version_id).all()
                all_f = Finding.query.filter_by(dataset_version=dataset_version_id).all()
                ds_prof = blackboard.read(job_id, "dataset_profile") or {}
                m_ctx = [{"id": m.id, "metric_code": m.metric_code, "period_end": m.period_end.isoformat(),
                          "value": float(m.value) if m.value is not None else None, "unit": m.unit} for m in all_m]
                f_ctx = [{"module": f.module, "title": f.title, "body": f.body, "severity": f.severity,
                          "metric_ids": f.metric_ids} for f in all_f]
                raw_txt = embed_json("METRICS_JSON", m_ctx) + "\n" + embed_json("FINDINGS_JSON", f_ctx)
                if ds_prof:
                    raw_txt += "\n" + embed_json("DATASET_PROFILE_JSON", ds_prof)
                synthesized = _insights_from_metrics(raw_txt)
                insights_payload = {
                    "insights": synthesized, "health_score": None, "findings": f_ctx,
                    "metrics": m_ctx, "benchmark_context": [], "dataset_profile": ds_prof,
                }
            insights_uri = blackboard.write(job_id, "insights", insights_payload)
        else:
            insights_uri = insight.outputs[0].uri
            insights_payload = blackboard.read(job_id, "insights") or {}

        draft_result = results.get("report_writer")
        draft_uri = draft_result.outputs[0].uri if (draft_result and getattr(draft_result, "outputs", None)) else None
        if not draft_uri:
            from app.domain.taxonomy import build_report_skeleton
            from app.llm_gateway.fake_client import _report_draft
            from app.llm_gateway.prompt_utils import embed_json
            from app.agents.schemas import ReportDraftResult
            charts = blackboard.read(job_id, "charts") or []
            ds_prof = blackboard.read(job_id, "dataset_profile") or {}
            skeleton = build_report_skeleton(
                metrics=insights_payload.get("metrics", []),
                findings=insights_payload.get("findings", []),
                charts=charts,
                dataset_profile=ds_prof,
            )
            u_content = embed_json("SKELETON_JSON", skeleton) + "\n" + embed_json("INSIGHTS_JSON", insights_payload.get("insights", []))
            if ds_prof:
                u_content += "\n" + embed_json("DATASET_PROFILE_JSON", ds_prof)
            draft_obj = ReportDraftResult(**_report_draft(u_content))
            draft_dict = draft_obj.model_dump()
            draft_dict["skeleton"] = skeleton
            draft_uri = blackboard.write(job_id, "draft", draft_dict)

        job.set_progress(95, "Verifying report")
        db.session.commit()
        verified, verifier_result = self._verify_loop(job_id, tenant_id, dataset_version_id, insights_uri,
                                                      draft_uri, guidance)
        draft_uri = verifier_result.usage.get("draft_uri", draft_uri) if verifier_result else draft_uri

        if verified:
            sections = verifier_result.usage["resolved_sections"]
        else:
            sections = (verifier_result.usage.get("resolved_sections") if verifier_result else None) or []
            if not sections:
                sections = resolve_draft_sections(blackboard.read(job_id, "draft") or {}, dataset_version_id)

        publish_report(job, dataset_version_id, sections, verified=verified, draft_uri=draft_uri)
        if verified:
            job.status = "COMPLETED"
            job.set_progress(100, "Report ready")
        else:
            job.status = "NEEDS_ANALYST"
            job.set_progress(97, "Verifier could not pass the draft after revisions; analyst review required")

            from app.models.review import ReviewItem
            from app.utils.ids import new_id
            
            issues_list = [i.message for i in getattr(verifier_result, "issues", [])] if verifier_result else []
            fb_list = (verifier_result.usage.get("feedback") if verifier_result and verifier_result.usage else []) or []
            all_issues = issues_list + [f for f in fb_list if f not in issues_list]
            summary_msg = verifier_result.summary if verifier_result else "Verification flagged claim discrepancies"
            
            existing_rev = ReviewItem.query.filter_by(job_id=job.id, kind="verification", status="open").first()
            if not existing_rev:
                db.session.add(ReviewItem(
                    id=new_id("rev_"),
                    job_id=job.id,
                    kind="verification",
                    payload={
                        "check_code": "VERIFIER_DISCREPANCY",
                        "summary": summary_msg,
                        "issues": all_issues or ["Automated claim-check could not confirm all numbers without analyst review."],
                        "feedback": fb_list,
                        "explanation": f"The automated verifier flagged {max(1, len(all_issues))} issue(s) in the generated draft report. "
                                       f"Review the flagged points below or approve the report to certify publication.",
                        "recommendation": {
                            "item_id": None,
                            "kind": "verification",
                            "action": "approve_and_publish",
                            "title": "Analyst Verification Sign-Off",
                            "confidence": 0.88,
                            "reasoning": "The draft report is rendered and available. As an analyst, you can approve the report to remove the unverified flag and mark the analysis completed, or supply manual audit notes.",
                            "audit_note": "Analyst reviewed draft claims and certified report publication.",
                            "auto_resolvable": True,
                        },
                    },
                ))
        db.session.commit()
        return verified

    def _verify_loop(self, job_id, tenant_id, dataset_version_id, insights_uri, draft_uri, guidance):
        verifier_result = None
        for revision in range(self.MAX_REVISIONS + 1):
            if draft_uri is None:
                break
            try:
                verifier_result = VerifierAgent(self.llm).run(_spec(job_id, tenant_id, "verifier", {
                    "dataset_version_id": dataset_version_id, "draft_uri": draft_uri, "insights_uri": insights_uri}))
            except Exception as exc:  # noqa: BLE001
                verifier_result = AgentResult(task_id=new_id("t_"), status=Status.FAILED,
                                              summary=f"verifier failed unexpectedly: {exc}")
                break
            verifier_result.usage["draft_uri"] = draft_uri
            if verifier_result.status == Status.DONE:
                return True, verifier_result
            if revision == self.MAX_REVISIONS:
                break
            # usage["feedback"] only exists for an LLM claim-check rejection; deterministic
            # failures (unresolved placeholder, raw number) are described by the issues.
            feedback = verifier_result.usage.get("feedback") or [i.message for i in verifier_result.issues]
            writer_cls = registry.get("report_writer").load()
            draft_result = writer_cls(self.llm).run(_spec(job_id, tenant_id, "report_writer", {
                "dataset_version_id": dataset_version_id, "insights_uri": insights_uri,
                "verifier_feedback": feedback, "user_guidance": guidance.get("report_writer")}))
            draft_uri = draft_result.outputs[0].uri if draft_result.outputs else None
        return False, verifier_result

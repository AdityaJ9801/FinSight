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

        results = {k: _as_result(v, k) if isinstance(v, NodeFailure) else v
                   for k, v in run_dag(nodes, app=self.app, max_workers=4, on_complete=on_complete).items()}

        insight = results["insight_reasoner"]
        if not insight.outputs:
            # No meaningful placeholder exists for "the model's synthesized insights" --
            # stop clearly rather than pushing a report through with no analysis behind it.
            job.status = "NEEDS_ANALYST"
            job.set_progress(88, f"Insight generation failed: {insight.summary or 'no output'}")
            db.session.commit()
            return False
        insights_uri = insight.outputs[0].uri

        draft_result = results["report_writer"]
        draft_uri = draft_result.outputs[0].uri if draft_result.outputs else None

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
            job.set_progress(97, "Verifier could not pass the draft after revisions; an unverified draft "
                                 "report is available for download")
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

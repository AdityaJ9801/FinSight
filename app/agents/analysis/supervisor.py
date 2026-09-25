from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask

from app.agents.base import AgentResult, Status, TaskSpec
from app.extensions import db
from app.orchestrator.templates import modules_for
from app.utils.ids import new_id


def _run_module(app: Flask, llm, job_id: str, tenant_id: str, dataset_version_id: str, agent_cls,
                 guidance: dict[str, str] | None = None) -> AgentResult:
    with app.app_context():
        agent = agent_cls(llm)
        spec = TaskSpec(
            task_id=new_id("t_"), job_id=job_id, tenant_id=tenant_id, agent=agent.name,
            goal=f"{agent.name} analysis for dataset {dataset_version_id}",
            params={"dataset_version_id": dataset_version_id, "user_guidance": (guidance or {}).get(agent.name)},
        )
        try:
            return agent.run(spec)
        except Exception as exc:
            # One module timing out (e.g. an overloaded LLM endpoint under the 5-way
            # concurrent fan-out here) must not discard the other four modules' results --
            # caught against a live model that occasionally exceeded the HTTP timeout.
            return AgentResult(task_id=spec.task_id, status=Status.FAILED,
                                summary=f"{agent.name} failed unexpectedly: {exc}")


class AnalysisSupervisor:
    name = "analysis_supervisor"

    def __init__(self, app: Flask, llm):
        self.app = app
        self.llm = llm

    def run_stage(self, job, dataset_version_id: str, guidance: dict[str, str] | None = None) -> bool:
        """guidance: {agent_name: note} from orchestrator.apply_pending_instructions, e.g.
        {"risk": "..."} -- passed through to whichever module(s) it names."""
        job.set_progress(75, "Running analysis modules")
        db.session.commit()

        module_agents = modules_for(job.plan_template)
        results = {}
        with ThreadPoolExecutor(max_workers=len(module_agents)) as pool:
            futures = {
                pool.submit(_run_module, self.app, self.llm, job.id, job.tenant_id, dataset_version_id, cls, guidance): cls.name
                for cls in module_agents
            }
            for future in as_completed(futures):
                results[futures[future]] = future.result()

        done_count = sum(1 for r in results.values() if r.status == Status.DONE)
        job.status = "SYNTHESIZING" if done_count > 0 else "PARTIAL"
        job.set_progress(85, f"Analysis complete: {done_count}/{len(module_agents)} modules produced findings")
        db.session.commit()

        # Gate: at least one module must have produced usable output. A fully empty
        # analysis stage (e.g. no recognizable statements at all) blocks delivery.
        return done_count > 0

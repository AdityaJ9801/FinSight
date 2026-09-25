"""Interactive QA agent (design doc §6.9). Called synchronously from the API (not part of
the job DAG) since answers need to be fast. Routing is a real LLM call; the "text-to-SQL"
step is intentionally the simplified {view, filters} form from tools/sql_tool.py rather
than free-form SQL generation -- see that module's docstring for why.
"""
from __future__ import annotations

import json

from app.agents.base import AgentResult, ArtifactRef, Status, TaskSpec, WorkerAgent
from app.agents.schemas import QAAnswerResult, RouteDecision
from app.extensions import db
from app.llm_gateway import prompts
from app.llm_gateway.prompt_utils import embed_json
from app.models.dataset import DatasetVersion
from app.models.document import Document
from app.domain.financial_intelligence import build_cfo_diagnostic_trace, resolve_metric_tree
from app.models.finding import Finding
from app.tools.calc.metrics import REGISTRY
from app.utils import storage

_CONVERSATIONAL_WORDS = {
    "ok", "okay", "thanks", "thank you", "great", "got it", "understood",
    "yes", "sure", "cool", "noted", "continue", "hello", "hi", "hey",
}


class QAAgent(WorkerAgent):
    name = "qa"
    allowed_tools = ["sql.query_readonly", "vector.search", "web.search"]

    def answer(
        self,
        tenant_id: str,
        dataset_version_id: str,
        question: str,
        history: list[dict] | None = None,
    ) -> dict:
        q_clean = question.strip().lower().rstrip(".!?,")
        if q_clean in _CONVERSATIONAL_WORDS:
            return {
                "answer": (
                    "Glad that was helpful! Let me know if you would like more details on specific "
                    "financial metrics, want to explore the visual charts, or need to re-run any "
                    "analysis module with new assumptions."
                ),
                "citations": [],
                "route": "report_lookup",
            }

        dataset_version = db.session.get(DatasetVersion, dataset_version_id)
        job_id = dataset_version.job_id if dataset_version else None

        route_prompt = [{"role": "system", "content": prompts.QA_ROUTER}]
        if history:
            for turn in history[-4:]:
                role = turn.get("role") or "user"
                content = turn.get("content") or ""
                if content:
                    route_prompt.append({"role": role, "content": content})
        route_prompt.append({"role": "user", "content": question})

        route: RouteDecision = self.call_llm(route_prompt, schema=RouteDecision)

        if route.route == "out_of_scope":
            return {
                "answer": (
                    "That's outside what I can answer from this dataset. I can help with specific metric "
                    "calculations, uploaded statement disclosures, report findings, visual charts, "
                    "or guide you on re-running analysis modules."
                ),
                "citations": [],
                "route": route.route,
            }

        if route.route == "action_request":
            return {
                "answer": (
                    "To recompute analysis with new assumptions (e.g. excluding one-off items or adjusting "
                    "projections) or regenerate the report, use the Chat Assistant to re-run the relevant "
                    "agent (e.g. 'redo the risk score excluding one-off item' or 'rerun report_writer')."
                ),
                "citations": [],
                "route": route.route,
            }

        rows: list[dict] = []
        chunks: list[dict] = []
        charts_data: list[dict] = []
        report_data: list[dict] = []

        # Load available charts if present for this job
        all_charts: list[dict] = []
        if job_id:
            charts_path = f"{job_id}/delivery/charts.json"
            if storage.resolve(charts_path).exists():
                try:
                    all_charts = json.loads(storage.resolve(charts_path).read_text())
                except Exception:
                    all_charts = []

        matched_tree = resolve_metric_tree(question)

        if route.route == "chart_lookup":
            # Match specific chart if named in question, otherwise provide summary of all charts
            q_low = question.lower()
            matching_charts = [
                c for c in all_charts
                if any(w in c.get("title", "").lower() for w in q_low.split() if len(w) > 3)
            ]
            selected = matching_charts or all_charts
            charts_data = [
                {
                    "chart_id": c.get("chart_id"),
                    "title": c.get("title"),
                    "caption": c.get("caption", ""),
                    "chart_type": (c.get("spec") or {}).get("chart_type"),
                    "labels": (c.get("spec") or {}).get("labels"),
                    "series": (c.get("spec") or {}).get("series"),
                }
                for c in selected[:6]
            ]
            if not charts_data:
                rows = self.call_tool("sql.query_readonly", view="v_metrics", filters={"dataset_version": dataset_version_id}, limit=10)

        elif route.route == "sql":
            matched_code = next(
                (code for code in REGISTRY if code.replace("_", " ") in question.lower() or code in question.lower()),
                None,
            )
            if not matched_code and matched_tree and matched_tree.metric_code in REGISTRY:
                matched_code = matched_tree.metric_code
            filters = {"dataset_version": dataset_version_id}
            if matched_code:
                filters["metric_code"] = matched_code
            rows = self.call_tool("sql.query_readonly", view="v_metrics", filters=filters, limit=20)

        elif route.route == "document_rag":
            document_ids = [d.id for d in Document.query.filter_by(job_id=job_id).all()] if job_id else []
            chunks = self.call_tool(
                "vector.search", tenant_id=tenant_id, query=question, top_k=5, document_ids=document_ids
            )

        elif route.route == "report_lookup":
            findings = Finding.query.filter_by(dataset_version=dataset_version_id).limit(15).all()
            report_data = [{"module": f.module, "title": f.title, "body": f.body, "severity": f.severity} for f in findings]
            if job_id:
                insights_path = f"{job_id}/delivery/insights.json"
                if storage.resolve(insights_path).exists():
                    try:
                        ins_payload = json.loads(storage.resolve(insights_path).read_text())
                        for item in ins_payload.get("insights", [])[:5]:
                            report_data.append({"module": "insight", "title": item.get("title"), "body": item.get("body")})
                    except Exception:
                        pass
            # Provide high-level chart titles so report overview has complete context
            if all_charts:
                charts_data = [{"chart_id": c.get("chart_id"), "title": c.get("title"), "caption": c.get("caption", "")} for c in all_charts[:4]]

        prompt_content = f"Question: {question}"
        if rows:
            prompt_content += "\n" + embed_json("ROWS_JSON", rows)
        if chunks:
            prompt_content += "\n" + embed_json("CHUNKS_JSON", chunks)
        if charts_data:
            prompt_content += "\n" + embed_json("CHARTS_JSON", charts_data)
        if report_data:
            prompt_content += "\n" + embed_json("REPORT_JSON", report_data)

        # Virtual CFO Diagnostic Compendium drill-down
        if matched_tree:
            q_low = question.lower()
            direction = (
                "decline"
                if any(w in q_low for w in ("drop", "fall", "declin", "down", "deteriorat", "loss", "compress", "low"))
                else ("increase" if any(w in q_low for w in ("rise", "increas", "up", "grow", "expand", "high")) else "change")
            )
            diag_trace = build_cfo_diagnostic_trace(matched_tree.metric_id, direction=direction)
            prompt_content += "\n" + embed_json("DIAGNOSTIC_TREE_JSON", diag_trace)

        compose_prompt = [
            {"role": "system", "content": prompts.QA_COMPOSER},
            {"role": "user", "content": prompt_content},
        ]
        result: QAAnswerResult = self.call_llm(compose_prompt, schema=QAAnswerResult, tier="reasoning")
        return {"answer": result.answer, "citations": result.citations, "route": route.route}

    def execute(self, spec: TaskSpec) -> AgentResult:
        result = self.answer(spec.tenant_id, spec.params["dataset_version_id"], spec.params["question"])
        return AgentResult(
            task_id=spec.task_id, status=Status.DONE,
            outputs=[ArtifactRef(id="qa_answer", kind="text", uri="inline")],
            summary=result["answer"][:500], confidence=0.7,
        )

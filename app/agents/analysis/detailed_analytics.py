"""Detailed Analytics agent (analysis stage): the statement-level analysis behind the
report's "Detailed Statement Analysis" narrative, its supporting tables and several charts.

Deterministic first (design principle 3): horizontal/common-size analysis, DuPont, CAGR,
the PAT bridge, net debt and bank analytics are all computed by tools/calc/detailed_analysis.py and
the detailed_analytics metric group. The LLM only writes findings that interpret them, citing
figures through {{m:code:period}} placeholders like every other module.
"""
from __future__ import annotations

from app.agents.analysis.common import AnalysisModuleAgent, metrics_json
from app.agents.base import AgentResult, ArtifactRef, Status, TaskSpec
from app.agents.schemas import FindingsSet
from app.domain.facts import load_facts_by_period
from app.extensions import db
from app.llm_gateway import prompts
from app.llm_gateway.prompt_utils import embed_json
from app.models.bank import BankTransaction
from app.models.finding import Finding
from app.orchestrator import blackboard
from app.tools.calc.detailed_analysis import growth_metric_dicts
from app.tools.calc.metrics import persist_metrics


def _drivers_context(analysis: dict) -> dict:
    """What the LLM needs to explain the analysis without re-deriving it: which lines moved
    PAT and in which direction, and which DuPont factor moved ROE -- directions and labels,
    the numbers themselves stay behind metric placeholders."""
    bridge = analysis.get("profit_bridge") or {}
    deltas = [s for s in bridge.get("steps", []) if s["kind"] == "delta"]
    deltas.sort(key=lambda s: abs(s["amount"]), reverse=True)
    dupont_rows = analysis.get("dupont", [])
    dupont_moves = {}
    if len(dupont_rows) >= 2:
        prev, curr = dupont_rows[-2], dupont_rows[-1]
        for k in ("net_margin", "asset_turnover", "equity_multiplier", "roe"):
            dupont_moves[k] = "up" if curr[k] > prev[k] else ("down" if curr[k] < prev[k] else "flat")
    bank = (analysis.get("bank") or {}).get("totals")
    return {
        "periods": analysis.get("periods", []),
        "pat_bridge_largest_drivers": [{"line": s["label"], "effect_on_pat": "positive" if s["amount"] > 0 else "negative"}
                                       for s in deltas[:4]],
        "dupont_direction_latest": dupont_moves,
        "bank_statement_present": bool(bank),
        "bank_net_flow_direction": (None if not bank else ("inflow" if bank["net"] >= 0 else "outflow")),
    }


class DetailedAnalyticsAgent(AnalysisModuleAgent):
    name = "detailed_analytics"
    module_label = "detailed_analytics"
    allowed_tools = ["metrics.compute", "analysis.detailed", "sql.query_readonly"]

    def execute(self, spec: TaskSpec) -> AgentResult:
        dataset_version_id = spec.params["dataset_version_id"]
        facts = load_facts_by_period(dataset_version_id)
        txns = [{"txn_date": t.txn_date.isoformat(), "narration": t.narration, "debit": float(t.debit or 0),
                 "credit": float(t.credit or 0), "balance": float(t.balance) if t.balance is not None else None}
                for t in BankTransaction.query.filter_by(dataset_version=dataset_version_id).all()]
        # A bank-statement-only analysis has no statement facts but still gets bank analytics
        # (monthly flows, top counterparties); only skip when there's nothing at all to analyse.
        if not facts and not txns:
            return AgentResult(task_id=spec.task_id, status=Status.PARTIAL, confidence=0.2,
                               summary="Not applicable: no statement figures or bank transactions to analyse.")
        analysis = self.call_tool("analysis.detailed", facts_by_period=facts, transactions=txns)
        blackboard.write(spec.job_id, "detailed_analysis", analysis)

        metric_rows = self.compute_group_metrics(dataset_version_id)
        metric_rows += persist_metrics(dataset_version_id, growth_metric_dicts(analysis))

        n_lines = sum(len(v) for v in analysis["statements"].values())
        summary = (f"Detailed analysis: {n_lines} statement lines across {len(analysis['periods'])} period(s), "
                   f"{len(analysis['dupont'])} DuPont period(s), {len(analysis['growth'])} CAGR series"
                   + (", PAT bridge" if analysis.get("profit_bridge") else "")
                   + (f", {analysis['bank']['totals']['months']} months of bank flows" if analysis["bank"]["totals"] else ""))
        if not metric_rows:
            return AgentResult(task_id=spec.task_id, status=Status.PARTIAL, confidence=0.5,
                               outputs=[ArtifactRef(id="detailed_analysis", kind="dataset", uri=blackboard.uri(spec.job_id, "detailed_analysis"))],
                               summary=summary + " (no detailed_analytics metrics computable from the accounts present).")

        user_content = embed_json("METRICS_JSON", metrics_json(metric_rows)) + "\n" + \
            embed_json("DETAILED_ANALYSIS_CONTEXT_JSON", _drivers_context(analysis))
        if spec.params.get("user_guidance"):
            user_content += "\n" + embed_json("USER_GUIDANCE_JSON", spec.params["user_guidance"])
        findings: FindingsSet = self.call_llm(
            [{"role": "system", "content": prompts.ANALYSIS_MODULE}, {"role": "user", "content": user_content}],
            schema=FindingsSet, tier="reasoning")
        for item in findings.findings:
            db.session.add(Finding(dataset_version=dataset_version_id, module=self.module_label, severity=item.severity,
                                   title=item.title, body=item.body, metric_ids=item.metric_ids, confidence=0.85))
        db.session.commit()

        return AgentResult(
            task_id=spec.task_id, status=Status.DONE, confidence=0.9,
            outputs=[ArtifactRef(id="detailed_analysis", kind="dataset", uri=blackboard.uri(spec.job_id, "detailed_analysis")),
                     ArtifactRef(id=dataset_version_id, kind="metric_set", uri="db://metrics", row_count=len(metric_rows))],
            summary=summary + f"; {len(metric_rows)} metric points, {len(findings.findings)} findings.",
        )

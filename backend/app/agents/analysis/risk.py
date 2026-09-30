from __future__ import annotations

from app.agents.base import AgentResult, ArtifactRef, Status, TaskSpec, WorkerAgent
from app.agents.schemas import FindingsSet
from app.domain.facts import load_facts_by_period
from app.extensions import db
from app.llm_gateway import prompts
from app.llm_gateway.prompt_utils import embed_json
from app.models.bank import BankTransaction
from app.models.finding import Finding
from app.tools.calc.bank_metrics import compute_bank_metrics, transactions_as_dicts
from app.tools.calc.metrics import compute_all, persist_metrics

# Computed directly from facts rather than read from the `metrics` table: risk runs
# concurrently with the ratio/cash_wc modules (§3.3 fan-out), so it can't assume their
# output has been persisted yet. Self-contained also means risk scoring still works if
# another module fails outright.
_RISK_INPUT_CODES = {"current_ratio", "debt_to_equity", "interest_coverage", "net_profit_margin", "dso"}
_BANK_RISK_CODES = {"bank_cash_cover_months", "bank_min_balance", "bank_top_payer_share", "bank_negative_month_share"}


class RiskAnomalyAgent(WorkerAgent):
    name = "risk"
    allowed_tools = ["risk.score", "anomaly.detect", "sandbox.run_python"]

    def execute(self, spec: TaskSpec) -> AgentResult:
        dataset_version_id = spec.params["dataset_version_id"]

        facts_by_period = load_facts_by_period(dataset_version_id)
        transactions = BankTransaction.query.filter_by(dataset_version=dataset_version_id).all()
        if not facts_by_period and not transactions:
            return AgentResult(task_id=spec.task_id, status=Status.PARTIAL,
                                summary="No statements or bank transactions available to score risk.", confidence=0.2)

        latest_values: dict[str, float] = {}
        latest_period = None
        if facts_by_period:
            latest_period = max(facts_by_period.keys())
            latest_values = {
                m["metric_code"]: m["value"] for m in compute_all(facts_by_period)
                if m["metric_code"] in _RISK_INPUT_CODES and m["period_end"] == latest_period
            }
        if transactions:
            bank = compute_bank_metrics(transactions_as_dicts(transactions))
            bank_end = max(m["period_end"] for m in bank)
            latest_values.update({m["metric_code"]: m["value"] for m in bank
                                  if m["metric_code"] in _BANK_RISK_CODES and m["period_end"] == bank_end})
            latest_period = max(latest_period, bank_end) if latest_period else bank_end

        risk_result = self.call_tool("risk.score", metrics=latest_values)

        txn_dicts = [{"row_idx": t.id, "narration": t.narration or "", "debit": float(t.debit or 0),
                      "credit": float(t.credit or 0)} for t in transactions]
        anomalies = self.call_tool("anomaly.detect", transactions=txn_dicts) if txn_dicts else []

        risk_metric = persist_metrics(dataset_version_id, [{
            "metric_code": "risk_score", "period_end": latest_period, "value": risk_result["risk_score"],
            "unit": "pts", "formula_version": "1.0", "inputs": list(latest_values.keys()),
        }])

        context = {"risk": risk_result, "anomalies": anomalies[:20]}
        user_content = (embed_json("METRICS_JSON", [{
            "id": risk_metric[0].id, "metric_code": "risk_score", "period_end": latest_period.isoformat(),
        }]) + "\n" + embed_json("CONTEXT_JSON", context))
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
                dataset_version=dataset_version_id, module="risk_anomaly", severity=item.severity,
                title=item.title, body=item.body, metric_ids=item.metric_ids, confidence=0.75,
            ))
        if not findings_set.findings and risk_result["drivers"]:
            for driver in risk_result["drivers"]:
                db.session.add(Finding(
                    dataset_version=dataset_version_id, module="risk_anomaly", severity="warn",
                    title=f"Risk driver: {driver['metric_code']}", body=driver["reason"],
                    metric_ids=[risk_metric[0].id],
                ))
        db.session.commit()

        return AgentResult(
            task_id=spec.task_id, status=Status.DONE,
            outputs=[ArtifactRef(id=dataset_version_id, kind="metric_set", uri="db://metrics")],
            summary=f"Risk band: {risk_result['band']} (score {risk_result['risk_score']}); "
                    f"{len(anomalies)} transaction anomaly flag(s).",
            confidence=0.8,
        )

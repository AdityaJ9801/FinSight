from __future__ import annotations

from app.agents.base import AgentResult, ArtifactRef, Issue, Status, TaskSpec, WorkerAgent
from app.agents.schemas import ExplanationResult
from app.domain.facts import load_facts_by_period
from app.domain.validation_rules import check_bank_running, check_duplicates, run_statement_checks
from app.extensions import db
from app.llm_gateway import prompts
from app.models.bank import BankTransaction
from app.models.document import Document
from app.models.validation import ValidationResult


class ReconcilerAgent(WorkerAgent):
    name = "reconciler"
    allowed_tools = ["recon.run_checks", "sql.query_readonly"]

    def execute(self, spec: TaskSpec) -> AgentResult:
        dataset_version_id = spec.params["dataset_version_id"]

        results = run_statement_checks(load_facts_by_period(dataset_version_id))

        transactions = BankTransaction.query.filter_by(dataset_version=dataset_version_id).all()
        if transactions:
            txn_dicts = [{"row_idx": t.id, "txn_date": t.txn_date.isoformat(), "debit": float(t.debit or 0),
                          "credit": float(t.credit or 0), "balance": float(t.balance) if t.balance is not None else None}
                         for t in transactions]
            bank_check = check_bank_running(txn_dicts)
            if bank_check:
                results.append(bank_check)

        docs = Document.query.filter_by(job_id=spec.job_id).all()
        results.append(check_duplicates([d.sha256 for d in docs]))

        failed: list[dict] = []
        for r in results:
            explanation = None
            if r["status"] == "fail":
                prompt = [
                    {"role": "system", "content": prompts.RECONCILER_EXPLAINER},
                    {"role": "user", "content": f"check_code={r['check_code']} expected={r.get('expected')} "
                                                 f"actual={r.get('actual')} diff={r.get('diff')} details={r.get('details')}"},
                ]
                explanation_result: ExplanationResult = self.call_llm(prompt, schema=ExplanationResult)
                explanation = explanation_result.explanation
                failed.append({**r, "explanation": explanation})

            db.session.add(ValidationResult(
                dataset_version=dataset_version_id, check_code=r["check_code"], status=r["status"],
                expected=r.get("expected"), actual=r.get("actual"), diff=r.get("diff"),
                details={**(r.get("details") or {}), "explanation": explanation},
            ))
        db.session.commit()

        issues = [Issue(severity="error", code=f["check_code"], message=f.get("explanation") or "check failed") for f in failed]
        status = Status.NEEDS_REVIEW if failed else Status.DONE

        return AgentResult(
            task_id=spec.task_id, status=status,
            outputs=[ArtifactRef(id=dataset_version_id, kind="dataset", uri="db://validation_results")],
            summary=f"Ran {len(results)} reconciliation checks, {len(failed)} failed.",
            confidence=1.0 if not failed else 0.5,
            issues=issues,
            usage={"failed_checks": failed},
        )

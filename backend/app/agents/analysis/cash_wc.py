from app.agents.analysis.common import AnalysisModuleAgent
from app.models.bank import BankTransaction
from app.tools.calc.bank_metrics import compute_bank_metrics, transactions_as_dicts
from app.tools.calc.metrics import persist_metrics


class CashWorkingCapitalAgent(AnalysisModuleAgent):
    name = "cash_wc"
    module_label = "cash_working_capital"

    def compute_group_metrics(self, dataset_version_id: str) -> list:
        # Statement-based working-capital metrics (DSO/DIO/DPO/CCC/FCF) when a balance sheet
        # and P&L are present, plus bank-statement cash metrics when transactions are -- so a
        # bank-statement-only analysis still produces a real cash view instead of nothing.
        rows = super().compute_group_metrics(dataset_version_id)
        txns = BankTransaction.query.filter_by(dataset_version=dataset_version_id).all()
        if txns:
            rows += persist_metrics(dataset_version_id, compute_bank_metrics(transactions_as_dicts(txns)))
        return rows

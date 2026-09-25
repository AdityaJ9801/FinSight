import tempfile
from pathlib import Path

import pytest
from sqlalchemy import text

from app import create_app
from app.config import Config
from app.domain.coa import CANONICAL_ACCOUNTS
from app.extensions import db


class TestConfig(Config):
    TESTING = True
    LLM_BACKEND = "fake"
    WEB_SEARCH_ENABLED = False


@pytest.fixture()
def app():
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "test.db"
    TestConfig.SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
    TestConfig.STORAGE_ROOT = Path(tmp_dir) / "storage"

    flask_app = create_app(TestConfig)
    with flask_app.app_context():
        db.create_all()
        db.session.execute(text(
            "CREATE VIEW IF NOT EXISTS v_metrics AS "
            "SELECT id, dataset_version, metric_code, period_end, value, unit FROM metrics"
        ))
        db.session.execute(text(
            "CREATE VIEW IF NOT EXISTS v_findings AS "
            "SELECT id, dataset_version, module, severity, title, body, metric_ids FROM findings"
        ))
        db.session.execute(text(
            "CREATE VIEW IF NOT EXISTS v_statements_wide AS "
            "SELECT id, dataset_version, account_id, period_end, value, confidence FROM financial_facts"
        ))
        db.session.execute(text(
            "CREATE VIEW IF NOT EXISTS v_bank_monthly AS "
            "SELECT dataset_version, strftime('%Y-%m', txn_date) AS month, "
            "SUM(debit) AS total_debit, SUM(credit) AS total_credit, COUNT(*) AS txn_count "
            "FROM bank_transactions GROUP BY dataset_version, month"
        ))
        from app.models.account import Account

        for account_id, name, statement, parent_id, normal_balance in CANONICAL_ACCOUNTS:
            db.session.add(Account(id=account_id, name=name, statement=statement,
                                    parent_id=parent_id, normal_balance=normal_balance))
        db.session.commit()
        yield flask_app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()

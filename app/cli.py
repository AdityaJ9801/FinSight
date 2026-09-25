import click
from flask import Flask
from sqlalchemy import text

from app.domain.coa import CANONICAL_ACCOUNTS
from app.extensions import db

_VIEWS = {
    "v_metrics": """
        CREATE VIEW IF NOT EXISTS v_metrics AS
        SELECT id, dataset_version, metric_code, period_end, value, unit FROM metrics
    """,
    "v_findings": """
        CREATE VIEW IF NOT EXISTS v_findings AS
        SELECT id, dataset_version, module, severity, title, body, metric_ids FROM findings
    """,
    "v_statements_wide": """
        CREATE VIEW IF NOT EXISTS v_statements_wide AS
        SELECT id, dataset_version, account_id, period_end, value, confidence FROM financial_facts
    """,
    "v_bank_monthly": """
        CREATE VIEW IF NOT EXISTS v_bank_monthly AS
        SELECT dataset_version,
               strftime('%Y-%m', txn_date) AS month,
               SUM(debit) AS total_debit,
               SUM(credit) AS total_credit,
               COUNT(*) AS txn_count
        FROM bank_transactions
        GROUP BY dataset_version, month
    """,
}


def register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db():
        """Creates all tables, the read-only QA views, seeds the canonical CoA, and sets up
        the single default tenant/entity this direct (no-login) application runs under."""
        db.create_all()
        for name, sql in _VIEWS.items():
            db.session.execute(text(sql))
        from app.models.account import Account

        for account_id, name, statement, parent_id, normal_balance in CANONICAL_ACCOUNTS:
            if db.session.get(Account, account_id) is None:
                db.session.add(Account(
                    id=account_id, name=name, statement=statement,
                    parent_id=parent_id, normal_balance=normal_balance,
                ))
        db.session.commit()

        from app.utils.default_tenant import DEFAULT_ENTITY_ID, DEFAULT_TENANT_ID, ensure_default_context

        ensure_default_context()
        click.echo(f"Database initialized: tables, views, canonical CoA, and the default "
                   f"tenant ({DEFAULT_TENANT_ID}) / entity ({DEFAULT_ENTITY_ID}) are ready.")

    @app.cli.command("seed-demo")
    def seed_demo():
        """Deprecated alias for `init-db`'s default-tenant setup, kept so older muscle
        memory (`init-db && seed-demo`) still works. There's no login/demo user anymore."""
        from app.utils.default_tenant import DEFAULT_ENTITY_ID, DEFAULT_TENANT_ID, ensure_default_context

        ensure_default_context()
        click.echo(f"(seed-demo is deprecated; init-db already does this.) "
                   f"tenant_id={DEFAULT_TENANT_ID} entity_id={DEFAULT_ENTITY_ID}")

"""Agent registry, DAG executor, metric-id isolation across jobs, and the forecast period fix."""
import threading
import time
from datetime import date

import pytest

from app.agents import registry
from app.agents.analysis.forecast import _add_months
from app.extensions import db
from app.models.metric import Metric
from app.orchestrator.executor import CycleError, Node, NodeFailure, run_dag
from app.tools.calc.metrics import persist_metrics


def test_registry_classes_load_and_names_match():
    for desc in registry.AGENTS:
        if desc.class_path:
            assert desc.load().name == desc.name
        for dep in desc.depends_on:
            assert registry.get(dep).stage == desc.stage, f"{desc.name} depends across stages on {dep}"


def test_orchestrator_routing_table_is_derived_from_registry():
    from app.orchestrator.orchestrator import STAGE_AGENT_DESCRIPTIONS

    assert STAGE_AGENT_DESCRIPTIONS["analysis"]["detailed_analytics"] == registry.get("detailed_analytics").description
    assert "verifier" not in STAGE_AGENT_DESCRIPTIONS["delivery"]  # not steerable


def test_dag_runs_independent_nodes_in_parallel_and_respects_dependencies():
    started: dict[str, float] = {}
    lock = threading.Lock()

    def work(name, delay=0.2):
        def fn(deps):
            with lock:
                started[name] = time.monotonic()
            time.sleep(delay)
            return {"name": name, "deps": sorted(deps)}
        return fn

    t0 = time.monotonic()
    results = run_dag([Node("a", work("a")), Node("b", work("b")), Node("c", work("c", 0.0), ("a", "b"))])
    assert time.monotonic() - t0 < 0.39  # a and b overlapped
    assert results["c"]["deps"] == ["a", "b"]
    assert started["c"] >= max(started["a"], started["b"]) + 0.15


def test_dag_captures_failures_and_still_runs_dependents():
    def boom(_):
        raise RuntimeError("chart backend down")

    results = run_dag([Node("charts", boom), Node("writer", lambda deps: type(deps["charts"]).__name__, ("charts",))])
    assert isinstance(results["charts"], NodeFailure) and "chart backend down" in str(results["charts"])
    assert results["writer"] == "NodeFailure"


def test_dag_rejects_cycles_and_unknown_dependencies():
    with pytest.raises(CycleError):
        run_dag([Node("a", lambda d: 1, ("b",)), Node("b", lambda d: 1, ("a",))])
    with pytest.raises(ValueError):
        run_dag([Node("a", lambda d: 1, ("missing",))])


def test_metric_rows_are_isolated_per_dataset_version(app):
    """Two jobs covering the same period used to share metric ids ('m_<code>_<period>'):
    the second job re-pointed the first job's row at itself."""
    from app.models.dataset import DatasetVersion
    from app.models.job import Job
    from app.models.tenant import Tenant

    with app.app_context():
        db.session.add(Tenant(id="ten_x", name="x"))
        for n in ("1", "2"):
            db.session.add(Job(id=f"job_{n}", tenant_id="ten_x", goal="g"))
            db.session.add(DatasetVersion(id=f"dsv_{n}", job_id=f"job_{n}"))
        db.session.commit()
        m = {"metric_code": "current_ratio", "period_end": date(2024, 3, 31), "unit": "x", "formula_version": "1.0",
             "inputs": []}
        persist_metrics("dsv_1", [{**m, "value": 1.5}])
        persist_metrics("dsv_2", [{**m, "value": 0.9}])
        v1 = Metric.query.filter_by(dataset_version="dsv_1", metric_code="current_ratio").one()
        v2 = Metric.query.filter_by(dataset_version="dsv_2", metric_code="current_ratio").one()
        assert float(v1.value) == 1.5 and float(v2.value) == 0.9


@pytest.mark.parametrize("start,months,expected", [
    (date(2024, 3, 31), 12, date(2025, 3, 31)),
    (date(2024, 3, 31), 24, date(2026, 3, 31)),
    (date(2023, 12, 31), 3, date(2024, 3, 31)),
    (date(2024, 1, 31), 1, date(2024, 2, 29)),
    (date(2024, 1, 15), 1, date(2024, 2, 15)),
])
def test_forecast_periods_stay_on_the_fiscal_calendar(start, months, expected):
    assert _add_months(start, months) == expected

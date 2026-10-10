import time
import pytest
from flask import Flask
from app.extensions import db
from app.llm_gateway.client import RealLLMGateway
from app.agents.schemas import RouteDecision, QAAnswerResult
from app.agents.delivery.qa import QAAgent
from app.models.job import Job
from app.models.dataset import DatasetVersion
from app.orchestrator import blackboard
from app.tools.parsers.structure import parse_columnar_dataset
from app.tools.parsers import RawTable
import pandas as pd


def test_circuit_breaker_instant_fallback():
    # Gateway pointing to an unresponsive or invalid url
    gw = RealLLMGateway(
        base_url="https://invalid-unresponsive-host-test.local/v1",
        api_key="dummy",
        model_name="test-model",
    )
    # First call will fail quickly due to fail-fast timeout (2.5s) and trip circuit
    t0 = time.time()
    res1 = gw.complete([{"role": "user", "content": "hello"}], schema=RouteDecision)
    t1 = time.time()
    assert isinstance(res1, RouteDecision)

    # Second call MUST be instant (< 0.05 seconds) because circuit is now tripped open!
    t2 = time.time()
    res2 = gw.complete([{"role": "user", "content": "show ebitda margin"}], schema=RouteDecision)
    elapsed = time.time() - t2
    assert isinstance(res2, RouteDecision)
    assert elapsed < 0.05, f"Circuit breaker was not instant! Took {elapsed}s"


def test_qa_agent_instant_chart_generation(app):
    with app.app_context():
        # Setup mock job and dataset
        job = Job(id="job_instant_test", tenant_id="tenant_default", goal="Test goal", status="COMPLETED")
        dv = DatasetVersion(id="dv_instant_test", job_id=job.id, status="VALIDATED")
        db.session.add(job)
        db.session.add(dv)
        db.session.commit()

        # Seed structured dataset in blackboard
        grid = [
            ["Party Name", "Revenue"],
            ["Alpha Corp", 1000000.0],
            ["Beta LLC", 750000.0],
            ["Gamma Inc", 500000.0],
        ]
        parsed = parse_columnar_dataset(grid, header_idx=0, name="sales")
        blackboard.write(job.id, "structured_datasets", [parsed[0].dataset])

        # Test instant QA chart generation
        from app.llm_gateway.fake_client import FakeLLMGateway
        qa = QAAgent(FakeLLMGateway())

        t0 = time.time()
        res = qa.answer(job.tenant_id, dv.id, "plot revenue by party name")
        elapsed = time.time() - t0

        assert res.get("route") == "chart_lookup"
        assert res.get("chart") is not None
        assert "Revenue by Party Name" in res["chart"]["title"]
        assert res["chart"]["png_base64"] is not None
        # Must execute within 1 second (previously took 15-30s)
        assert elapsed < 1.0, f"Chart generation took too long: {elapsed}s"


def test_worker_settings_endpoint(client):
    # Test updating worker count and parallel flag via settings endpoint
    resp = client.post("/api/llm/config", json={
        "parallel_calls": True,
        "max_concurrent_requests": 12,
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["parallel_calls"] is True
    assert data["max_concurrent_requests"] == 12

    # Verify status reflects the updated worker count
    status_resp = client.get("/api/llm/status")
    assert status_resp.status_code == 200
    status_data = status_resp.get_json()
    assert status_data["parallel_calls"] is True
    assert status_data["max_concurrent_requests"] == 12


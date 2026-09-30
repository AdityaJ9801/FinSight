"""Convenience script: uploads the sample P&L/BS/cash flow/bank statement CSVs as one job
(no login -- this is a direct/local application), and polls until it completes (or needs
review).

Usage (with the Flask app and a Celery worker already running):
    python seed/upload_demo_job.py
"""
import sys
import time
from pathlib import Path

import requests

BASE_URL = "http://localhost:5000/api"
DATA_DIR = Path(__file__).parent / "data"
FILES = ["pnl.csv", "balance_sheet.csv", "cash_flow.csv", "bank_statement.csv"]


def main() -> None:
    files = [("files", (name, open(DATA_DIR / name, "rb"))) for name in FILES]
    resp = requests.post(
        f"{BASE_URL}/jobs", files=files,
        data={"goal": "Full financial analysis for demo entity", "plan_template": "full_analysis"},
    )
    resp.raise_for_status()
    job_id = resp.json()["job_id"]
    print(f"Created job {job_id}")

    for _ in range(120):
        status = requests.get(f"{BASE_URL}/jobs/{job_id}").json()
        print(f"  [{status['progress_pct']:>3}%] {status['stage']}/{status['status']}: {status['progress_message']}")
        if status["status"] in ("COMPLETED", "FAILED", "NEEDS_ANALYST", "AWAITING_REVIEW"):
            break
        time.sleep(2)
    else:
        print("Timed out waiting for job to finish.")
        sys.exit(1)

    if status["status"] == "AWAITING_REVIEW":
        items = requests.get(f"{BASE_URL}/review/items", params={"job_id": job_id}).json()
        print(f"Job needs review: {len(items)} item(s) open. See GET /api/review/items?job_id={job_id}")
    elif status["status"] == "COMPLETED":
        print(f"Report: {BASE_URL}/jobs/{job_id}/report?format=html")
        print(f"Task trace: {BASE_URL}/jobs/{job_id}/tasks")


if __name__ == "__main__":
    main()

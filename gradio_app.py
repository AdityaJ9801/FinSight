"""Gradio demo UI for the FinSight multi-agent pipeline. Talks to the Flask API only (over
HTTP, via `requests`) -- it never imports app.* directly, so it can run as its own
container against any FinSight API instance (see docker-compose.yml's `gradio` service).

No login: this is a direct/local application, not a multi-tenant SaaS -- every API call
resolves to the same fixed default tenant (see app/utils/default_tenant.py).

Five tabs:
  1. Run analysis     -- upload documents, kick off a job, watch the agent pipeline live
     (stage/status/progress plus a row-per-agent-task trace: intake, extract, map,
     reconcile, the 5 analysis modules, insight, chart spec, report writer, verifier).
  2. Review & Approve -- a job paused at 65%/AWAITING_REVIEW is waiting on a reconciliation
     check that didn't tie out, not hung; this is where you read it and accept it (or
     correct a specific low-confidence mapping) so the job resumes.
  3. Results          -- metrics, findings, the rendered report (inline HTML + DOCX/PDF).
  4. Ask a question   -- the QA agent (text-to-SQL / document RAG / report lookup).
  5. LLM & API Keys   -- configure/inspect which LLM provider is active.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

# Gradio reads GRADIO_TEMP_DIR at import time to pick its upload-cache directory
# (components/file.py writes uploads there via tempfile.NamedTemporaryFile). In a fresh
# container it doesn't reliably exist yet when the first upload comes in
# ("FileNotFoundError: /tmp/gradio/tmp..."), so this must run -- and the directory must
# exist -- BEFORE `import gradio`, not after.
_GRADIO_TEMP_DIR = os.environ.get("GRADIO_TEMP_DIR") or str(Path(tempfile.gettempdir()) / "gradio")
os.environ["GRADIO_TEMP_DIR"] = _GRADIO_TEMP_DIR
Path(_GRADIO_TEMP_DIR).mkdir(parents=True, exist_ok=True)

import gradio as gr  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:5000/api")
POLL_INTERVAL_S = 2
MAX_POLL_ITERATIONS = 900  # ~30 min ceiling at POLL_INTERVAL_S=2
TERMINAL_STATUSES = {"COMPLETED", "FAILED", "NEEDS_ANALYST", "AWAITING_REVIEW"}
TASKS_COLUMNS = ["time", "agent", "status", "confidence", "summary"]


def _empty_tasks_df() -> pd.DataFrame:
    return pd.DataFrame(columns=TASKS_COLUMNS)


def _tasks_dataframe(job_id: str) -> pd.DataFrame:
    resp = requests.get(f"{API_BASE_URL}/jobs/{job_id}/tasks", timeout=15)
    if resp.status_code != 200:
        return _empty_tasks_df()
    rows = resp.json()
    if not rows:
        return _empty_tasks_df()
    return pd.DataFrame([{
        "time": r["created_at"].split("T")[1][:8] if "T" in r["created_at"] else r["created_at"],
        "agent": r["agent"],
        "status": r["status"],
        "confidence": round(r["confidence"], 2) if r["confidence"] is not None else None,
        "summary": (r["summary"] or "")[:180],
    } for r in rows])


def run_job(files, goal, plan_template):
    """Generator: submits the job, then polls status + the per-agent task trace until the
    job reaches a terminal state, yielding an update on every poll so the UI shows the
    multi-agent pipeline working in near-real-time."""
    if not files:
        yield "Upload at least one document first.", 0, _empty_tasks_df(), "", "", ""
        return

    opened = [open(f, "rb") for f in files]
    try:
        file_tuples = [("files", (Path(f).name, fh)) for f, fh in zip(files, opened)]
        try:
            resp = requests.post(
                f"{API_BASE_URL}/jobs", files=file_tuples,
                data={"goal": goal or "Full financial analysis", "plan_template": plan_template},
                timeout=60,
            )
        except requests.RequestException as exc:
            yield f"Could not reach the API: {exc}", 0, _empty_tasks_df(), "", "", ""
            return
    finally:
        for fh in opened:
            fh.close()

    if resp.status_code not in (201, 503):
        yield f"Failed to create job ({resp.status_code}): {resp.text}", 0, _empty_tasks_df(), "", "", ""
        return
    body = resp.json()
    job_id = body["job_id"]
    if resp.status_code == 503:
        yield f"Job {job_id} created but the queue is unavailable: {body.get('error')}", 0, _empty_tasks_df(), job_id, "FAILED", body.get("error", "")
        return

    yield f"Job created: `{job_id}` -- queued.", 0, _empty_tasks_df(), job_id, "CREATED", ""

    for _ in range(MAX_POLL_ITERATIONS):
        time.sleep(POLL_INTERVAL_S)
        try:
            status_resp = requests.get(f"{API_BASE_URL}/jobs/{job_id}", timeout=15)
        except requests.RequestException:
            continue
        if status_resp.status_code != 200:
            continue
        status = status_resp.json()
        tasks_df = _tasks_dataframe(job_id)
        label = f"**[{status['stage']}] {status['status']}** -- {status['progress_message']}"
        yield label, status["progress_pct"], tasks_df, job_id, status["status"], status.get("error") or ""
        if status["status"] in TERMINAL_STATUSES:
            return

    yield "Timed out waiting for the job to finish (30 min).", 0, _tasks_dataframe(job_id), job_id, "TIMEOUT", ""


def load_results(job_id: str):
    empty = (pd.DataFrame(), pd.DataFrame(), "<p>Nothing loaded yet.</p>", None, None)
    if not job_id:
        return empty
    try:
        metrics_resp = requests.get(f"{API_BASE_URL}/jobs/{job_id}/metrics", timeout=15)
        findings_resp = requests.get(f"{API_BASE_URL}/jobs/{job_id}/findings", timeout=15)
    except requests.RequestException as exc:
        return pd.DataFrame(), pd.DataFrame(), f"<p>Could not reach the API: {exc}</p>", None, None

    metrics_df = pd.DataFrame(metrics_resp.json()) if metrics_resp.status_code == 200 else pd.DataFrame()
    findings_json = findings_resp.json() if findings_resp.status_code == 200 else []
    findings_df = pd.DataFrame(findings_json)[["module", "severity", "title", "body"]] if findings_json else pd.DataFrame()

    html_resp = requests.get(f"{API_BASE_URL}/jobs/{job_id}/report", params={"format": "html"}, timeout=30)
    html_content = html_resp.text if html_resp.status_code == 200 else \
        f"<p>Report not available yet ({html_resp.status_code}): {html_resp.text}</p>"

    docx_path = _download_report(job_id, "docx")
    pdf_path = _download_report(job_id, "pdf")
    return metrics_df, findings_df, html_content, docx_path, pdf_path


def _download_report(job_id: str, fmt: str) -> str | None:
    try:
        resp = requests.get(f"{API_BASE_URL}/jobs/{job_id}/report", params={"format": fmt}, timeout=30)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    path = Path(tempfile.gettempdir()) / f"{job_id}_report.{fmt}"
    path.write_bytes(resp.content)
    return str(path)


def _empty_recon_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["id", "check_code", "expected", "actual", "diff", "explanation"])


def _empty_mapping_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["id", "label", "suggested_account_id", "confidence"])


def load_review_items(job_id: str):
    if not job_id:
        return _empty_recon_df(), _empty_mapping_df(), "Enter a job id first (auto-filled after a run, on tab 1)."
    try:
        resp = requests.get(f"{API_BASE_URL}/review/items", params={"job_id": job_id}, timeout=15)
    except requests.RequestException as exc:
        return _empty_recon_df(), _empty_mapping_df(), f"Could not reach the API: {exc}"
    if resp.status_code != 200:
        return _empty_recon_df(), _empty_mapping_df(), f"Error ({resp.status_code}): {resp.text}"

    items = resp.json()
    recon = [i for i in items if i["kind"] != "mapping"]
    mapping = [i for i in items if i["kind"] == "mapping"]
    recon_df = pd.DataFrame([{
        "id": i["id"], "check_code": i["payload"].get("check_code"), "expected": i["payload"].get("expected"),
        "actual": i["payload"].get("actual"), "diff": i["payload"].get("diff"),
        "explanation": i["payload"].get("explanation"),
    } for i in recon]) if recon else _empty_recon_df()
    mapping_df = pd.DataFrame([{
        "id": i["id"], "label": i["payload"].get("label"),
        "suggested_account_id": i["payload"].get("suggested_account_id"),
        "confidence": i["payload"].get("confidence"),
    } for i in mapping]) if mapping else _empty_mapping_df()

    if not items:
        msg = "No open review items for this job -- it isn't waiting on review (or the job id is wrong)."
    else:
        msg = (
            f"**{len(recon)} blocking item(s)** (reconciliation) -- these are what's actually holding the "
            f"job at 65%/AWAITING_REVIEW. Use \"Accept & resume\" below once you've read them.\n\n"
            f"**{len(mapping)} informational item(s)** (low-confidence account mappings) -- already "
            f"auto-approved and NOT blocking the job; shown for transparency. Correct one below only if "
            f"you spot a wrong guess you want fixed for accuracy."
        )
    return recon_df, mapping_df, msg


def accept_reconciliation_and_resume(job_id: str):
    """Resolves every OPEN reconciliation review item for this job (the actual blocker
    behind AWAITING_REVIEW/65%), then polls the same way run_job does so progress keeps
    showing in this tab without switching back to tab 1."""
    if not job_id:
        yield "Enter a job id first.", 0, _empty_tasks_df(), _empty_recon_df(), _empty_mapping_df()
        return
    try:
        items_resp = requests.get(f"{API_BASE_URL}/review/items", params={"job_id": job_id}, timeout=15)
    except requests.RequestException as exc:
        yield f"Could not reach the API: {exc}", 0, _empty_tasks_df(), _empty_recon_df(), _empty_mapping_df()
        return
    if items_resp.status_code != 200:
        yield f"Error ({items_resp.status_code}): {items_resp.text}", 0, _empty_tasks_df(), _empty_recon_df(), _empty_mapping_df()
        return

    recon_items = [i for i in items_resp.json() if i["kind"] == "reconciliation"]
    if not recon_items:
        yield "No open reconciliation items to accept -- this job isn't blocked on one.", 0, \
            _empty_tasks_df(), _empty_recon_df(), _empty_mapping_df()
        return

    for item in recon_items:
        try:
            requests.post(f"{API_BASE_URL}/review/items/{item['id']}/resolve",
                          json={"note": "accepted via Gradio Review tab"}, timeout=15)
        except requests.RequestException:
            pass  # surfaced below by the item still showing "open" on the next Load

    yield f"Accepted {len(recon_items)} reconciliation item(s) -- resuming job...", 0, \
        _empty_tasks_df(), _empty_recon_df(), _empty_mapping_df()

    for _ in range(MAX_POLL_ITERATIONS):
        time.sleep(POLL_INTERVAL_S)
        try:
            status_resp = requests.get(f"{API_BASE_URL}/jobs/{job_id}", timeout=15)
        except requests.RequestException:
            continue
        if status_resp.status_code != 200:
            continue
        status = status_resp.json()
        tasks_df = _tasks_dataframe(job_id)
        label = f"**[{status['stage']}] {status['status']}** -- {status['progress_message']}"
        if status["status"] == "AWAITING_REVIEW":
            recon_df, mapping_df, _ = load_review_items(job_id)
            yield label + "\n\n(Still blocked -- a new/different item needs review; see below.)", \
                status["progress_pct"], tasks_df, recon_df, mapping_df
            return
        yield label, status["progress_pct"], tasks_df, _empty_recon_df(), _empty_mapping_df()
        if status["status"] in TERMINAL_STATUSES:
            return

    yield "Timed out waiting for the job to finish (30 min).", 0, _tasks_dataframe(job_id), \
        _empty_recon_df(), _empty_mapping_df()


def correct_mapping(review_item_id: str, account_id: str) -> str:
    if not review_item_id or not account_id:
        return "Enter both the review item id (from the table above) and the correct account id."
    try:
        resp = requests.post(f"{API_BASE_URL}/review/items/{review_item_id.strip()}/resolve",
                              json={"account_id": account_id.strip()}, timeout=15)
    except requests.RequestException as exc:
        return f"Could not reach the API: {exc}"
    if resp.status_code != 200:
        return f"Error ({resp.status_code}): {resp.text}"
    return f"Corrected to `{account_id.strip()}` -- remembered for future documents with this layout."


def ask_qa(job_id: str, question: str) -> str:
    if not job_id:
        return "Enter a job id (auto-filled after a run, on the first tab)."
    if not question:
        return "Enter a question."
    try:
        resp = requests.post(f"{API_BASE_URL}/qa", json={"job_id": job_id, "question": question}, timeout=90)
    except requests.RequestException as exc:
        return f"Could not reach the API: {exc}"
    if resp.status_code != 200:
        return f"Error ({resp.status_code}): {resp.text}"
    data = resp.json()
    citations = ", ".join(data.get("citations", [])) or "none"
    return f"**Route:** `{data['route']}`\n\n**Answer:** {data['answer']}\n\n**Citations:** {citations}"


def _llm_api_base() -> str:
    base = API_BASE_URL.rstrip("/")
    if base.endswith("/api"):
        return f"{base}/llm"
    return f"{base}/api/llm"


BACKEND_CHOICE_MAP = {
    "Auto (Smart: uses whichever API key is set)": "auto",
    "OpenAI Fast (gpt-4o-mini)": "openai",
    "OpenAI Reasoning (gpt-4o)": "openai_reasoning",
    "Gemini Fast (gemini-2.0-flash)": "gemini",
    "Gemini Reasoning (gemini-1.5-pro)": "gemini_reasoning",
    "Custom Endpoint (Real LLM)": "real",
    "Fake Mock (Offline / Tests)": "fake",
}
BACKEND_REV_MAP = {v: k for k, v in BACKEND_CHOICE_MAP.items()}


def get_llm_status_info():
    try:
        resp = requests.get(f"{_llm_api_base()}/status", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            keys = []
            if data["keys_configured"]["openai"]:
                keys.append(f"OpenAI: `{data['masked_keys']['openai']}`")
            if data["keys_configured"]["gemini"]:
                keys.append(f"Gemini: `{data['masked_keys']['gemini']}`")
            if data["keys_configured"]["custom"]:
                keys.append("Custom endpoint key set")
            keys_str = " | ".join(keys) if keys else "_No API keys detected (falling back to Fake mock)_"
            parallel_str = "Enabled" if data["parallel_calls"] else "Disabled"

            summary = (
                f"### Current LLM Status\n"
                f"- **Active Model:** `{data['active_model']}` ({data['resolved_backend']})\n"
                f"- **Configured Backend:** `{data['configured_backend']}`\n"
                f"- **Parallel Calls:** **{parallel_str}** (Max {data['max_concurrent_requests']} concurrent requests)\n"
                f"- **Configured Keys:** {keys_str}\n"
            )
            selected_choice = BACKEND_REV_MAP.get(data["configured_backend"], "Auto (Smart: uses whichever API key is set)")
            return summary, selected_choice, data["parallel_calls"]
    except Exception as exc:
        return f"Could not reach FinSight LLM API: {exc}", "Auto (Smart: uses whichever API key is set)", True
    return "LLM status unavailable", "Auto (Smart: uses whichever API key is set)", True


def save_llm_settings(backend_label: str, openai_key: str, gemini_key: str, parallel_calls: bool):
    backend = BACKEND_CHOICE_MAP.get(backend_label, "auto")
    payload = {"backend": backend, "parallel_calls": parallel_calls}
    if openai_key and openai_key.strip():
        payload["openai_api_key"] = openai_key.strip()
    if gemini_key and gemini_key.strip():
        payload["gemini_api_key"] = gemini_key.strip()
    try:
        resp = requests.post(f"{_llm_api_base()}/config", json=payload, timeout=10)
        if resp.status_code == 200:
            status_text, selected_choice, parallel = get_llm_status_info()
            return f"**Settings updated and saved to `.env` successfully!**\n\n{status_text}", "", ""
        return f"**Error updating config ({resp.status_code}):** {resp.text}", openai_key, gemini_key
    except Exception as exc:
        return f"**Failed to save settings:** {exc}", openai_key, gemini_key


with gr.Blocks(title="FinSight -- Multi-Agent Financial Analysis") as demo:
    gr.Markdown(
        "# FinSight -- Multi-Agent Financial Analysis\n"
        "Upload financial documents (P&L, balance sheet, cash flow, bank statement) and "
        "watch the orchestrator -> data/analysis/delivery supervisor -> worker agent "
        "pipeline run. Talks to the FinSight API at `" + API_BASE_URL + "`."
    )

    with gr.Tab("1. Run analysis"):
        files_input = gr.File(label="Financial documents (CSV / Excel / PDF)", file_count="multiple")
        with gr.Row():
            goal_input = gr.Textbox(label="Goal", value="Full financial analysis for demo entity", scale=3)
            template_input = gr.Dropdown(
                label="Plan template",
                choices=["full_analysis", "bank_statement_review", "gst_reconciliation", "lender_credit_memo"],
                value="full_analysis", scale=1,
            )
        run_btn = gr.Button("Run pipeline", variant="primary")

        progress_label = gr.Markdown("Idle.")
        progress_bar = gr.Slider(label="Progress %", minimum=0, maximum=100, value=0, interactive=False)
        with gr.Row():
            current_job_box = gr.Textbox(label="Job ID", interactive=False)
            job_status_box = gr.Textbox(label="Status", interactive=False)
        job_error_box = gr.Textbox(label="Error (if any)", interactive=False)

        gr.Markdown(
            "### Multi-agent task trace (live)\n"
            "One row per completed agent task -- data stage (intake -> extract -> map, per "
            "document/sheet/table, then reconcile), analysis stage (ratio/trend, cash & "
            "working capital, forecast, risk & anomaly, GST -- run in parallel), delivery "
            "stage (insight -> chart spec + report writer -> verifier)."
        )
        tasks_table = gr.Dataframe(headers=TASKS_COLUMNS, wrap=True)

        run_btn.click(
            run_job,
            inputs=[files_input, goal_input, template_input],
            outputs=[progress_label, progress_bar, tasks_table, current_job_box, job_status_box, job_error_box],
        )

    with gr.Tab("2. Review & Approve"):
        gr.Markdown(
            "### A job stuck at 65% (`AWAITING_REVIEW`) is paused here on purpose, not hung\n"
            "It's waiting on a **reconciliation** check that didn't tie out (e.g. recomputed "
            "vs. stated PAT) -- something a human should look at once, not every low-confidence "
            "mapping guess (those are auto-approved automatically and just logged below for "
            "transparency)."
        )
        review_job_id = gr.Textbox(label="Job ID")
        load_review_btn = gr.Button("Load review items", variant="secondary")
        review_status_md = gr.Markdown("Enter a job id and click \"Load review items\".")

        gr.Markdown("#### Blocking items (reconciliation) -- read the explanation, then accept if it's a known/acceptable gap")
        recon_table = gr.Dataframe(headers=["id", "check_code", "expected", "actual", "diff", "explanation"], wrap=True)
        accept_recon_btn = gr.Button("Accept all reconciliation items & resume job", variant="primary")
        accept_progress_md = gr.Markdown()
        accept_progress_bar = gr.Slider(label="Progress %", minimum=0, maximum=100, value=0, interactive=False)
        accept_tasks_table = gr.Dataframe(headers=TASKS_COLUMNS, wrap=True)

        gr.Markdown(
            "#### Informational items (low-confidence account mappings)\n"
            "Already auto-approved -- NOT blocking the job. Only fix one below if you spot a "
            "wrong guess and want it corrected (and remembered for future uploads with the "
            "same layout)."
        )
        mapping_table = gr.Dataframe(headers=["id", "label", "suggested_account_id", "confidence"], wrap=True)
        with gr.Row():
            correct_item_id = gr.Textbox(label="Review item id (copy from the id column above)")
            correct_account_id = gr.Textbox(label="Correct account id (e.g. BS.CA.CASH)")
        correct_btn = gr.Button("Correct this mapping")
        correct_result_md = gr.Markdown()

        load_review_btn.click(load_review_items, inputs=[review_job_id], outputs=[recon_table, mapping_table, review_status_md])
        accept_recon_btn.click(
            accept_reconciliation_and_resume, inputs=[review_job_id],
            outputs=[accept_progress_md, accept_progress_bar, accept_tasks_table, recon_table, mapping_table],
        )
        correct_btn.click(correct_mapping, inputs=[correct_item_id, correct_account_id], outputs=[correct_result_md])
        current_job_box.change(lambda x: x, inputs=current_job_box, outputs=review_job_id)

    with gr.Tab("3. Results"):
        job_id_input = gr.Textbox(label="Job ID")
        load_btn = gr.Button("Load results", variant="primary")
        metrics_table = gr.Dataframe(label="Metrics")
        findings_table = gr.Dataframe(label="Findings")
        report_html = gr.HTML(label="Report (HTML)")
        with gr.Row():
            docx_file = gr.File(label="Report (DOCX)")
            pdf_file = gr.File(label="Report (PDF)")

        load_btn.click(load_results, inputs=[job_id_input],
                        outputs=[metrics_table, findings_table, report_html, docx_file, pdf_file])
        current_job_box.change(lambda x: x, inputs=current_job_box, outputs=job_id_input)

    with gr.Tab("4. Ask a question"):
        qa_job_id = gr.Textbox(label="Job ID")
        qa_question = gr.Textbox(label="Question", value="What is the current ratio?")
        qa_btn = gr.Button("Ask", variant="primary")
        qa_answer = gr.Markdown()
        qa_btn.click(ask_qa, inputs=[qa_job_id, qa_question], outputs=qa_answer)
        current_job_box.change(lambda x: x, inputs=current_job_box, outputs=qa_job_id)

    with gr.Tab("5. LLM & API Keys"):
        gr.Markdown(
            "## LLM Model & API Key Configuration\n"
            "Upload or enter your OpenAI or Google Gemini API key below. "
            "FinSight will automatically use whichever model has an available API key, "
            "with parallel calls enabled for multi-agent speed."
        )
        status_display = gr.Markdown("Loading LLM status...")
        refresh_status_btn = gr.Button("Refresh Status", size="sm")

        with gr.Row():
            openai_key_input = gr.Textbox(
                label="OpenAI API Key (Upload/Paste here)",
                placeholder="sk-proj-...",
                type="password",
            )
            gemini_key_input = gr.Textbox(
                label="Google Gemini API Key (Upload/Paste here)",
                placeholder="AIzaSy...",
                type="password",
            )

        with gr.Row():
            backend_dropdown = gr.Dropdown(
                label="Active Model / Provider Selection",
                choices=list(BACKEND_CHOICE_MAP.keys()),
                value="Auto (Smart: uses whichever API key is set)",
            )
            parallel_chk = gr.Checkbox(label="Enable Parallel LLM Calls", value=True)

        save_llm_btn = gr.Button("Save & Apply Settings", variant="primary")
        save_result_box = gr.Markdown()

        save_llm_btn.click(
            save_llm_settings,
            inputs=[backend_dropdown, openai_key_input, gemini_key_input, parallel_chk],
            outputs=[save_result_box, openai_key_input, gemini_key_input],
        )
        refresh_status_btn.click(
            lambda: get_llm_status_info()[0],
            outputs=[status_display],
        )
        demo.load(
            get_llm_status_info,
            outputs=[status_display, backend_dropdown, parallel_chk],
        )


if __name__ == "__main__":
    demo.queue().launch(
        server_name="0.0.0.0",
        server_port=int(os.environ.get("GRADIO_PORT", "7860")),
        debug=True,
    )

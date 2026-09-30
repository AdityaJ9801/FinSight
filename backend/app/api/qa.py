from flask import Blueprint, jsonify, request

from app.agents.delivery.qa import QAAgent
from app.api.deps import current_tenant_id
from app.llm_gateway import get_llm_gateway
from app.models.job import Job

bp = Blueprint("qa", __name__)


@bp.post("")
def ask():
    data = request.get_json(force=True, silent=True) or {}
    job_id = data.get("job_id")
    question = data.get("question")
    if not job_id or not question:
        return jsonify(error="job_id and question are required"), 400

    job = Job.query.filter_by(id=job_id, tenant_id=current_tenant_id()).first()
    if job is None or job.dataset_version_id is None:
        return jsonify(error="not found"), 404

    history = data.get("history")
    agent = QAAgent(get_llm_gateway())
    result = agent.answer(current_tenant_id(), job.dataset_version_id, question, history=history)
    return jsonify(result)

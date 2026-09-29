"""GET /api/agents -- the agent registry (stage, label, icon, dependencies), used by the web UI
to label and group the live agent trace without hard-coding agent names."""
from flask import Blueprint, jsonify

from app.agents import registry as agent_registry

bp = Blueprint("agents", __name__)


@bp.get("")
def list_agents():
    return jsonify([a.to_public_dict() for a in agent_registry.AGENTS])

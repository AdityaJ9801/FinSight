from flask import Blueprint, jsonify

from app.domain.benchmarks import industries, load_benchmarks

bp = Blueprint("benchmarks", __name__)


@bp.get("/industries")
def list_industries():
    data = load_benchmarks()
    return jsonify({"source": data["source"], "as_of": data["as_of"], "industries": industries()})

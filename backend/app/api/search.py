from flask import Blueprint, current_app, jsonify, request

from app.tools.web_search import WebSearchError, web_search

bp = Blueprint("search", __name__)


@bp.get("")
def search():
    if not current_app.config.get("WEB_SEARCH_ENABLED"):
        return jsonify(error="web search is disabled (WEB_SEARCH_ENABLED=false)"), 503

    query = request.args.get("q")
    if not query:
        return jsonify(error="query parameter 'q' is required"), 400

    try:
        results = web_search(
            query,
            num_results=current_app.config["WEB_SEARCH_NUM_RESULTS"],
            lines_per_result=current_app.config["WEB_SEARCH_LINES_PER_RESULT"],
            timeout_s=current_app.config["WEB_SEARCH_TIMEOUT_S"],
        )
        return jsonify(results)
    except WebSearchError as exc:
        return jsonify(error=str(exc)), 502

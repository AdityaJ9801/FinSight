from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    # threaded=True matters here: the SSE endpoint (/api/jobs/<id>/stream) holds its worker
    # thread open while polling, and the dev server is single-threaded by default.
    app.run(debug=app.config.get("FLASK_DEBUG", True), port=5000, threaded=True)

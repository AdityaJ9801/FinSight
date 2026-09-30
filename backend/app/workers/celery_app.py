"""Celery entrypoint: `celery -A app.workers.celery_app worker --pool=solo -l info` (the
--pool=solo is required on Windows -- Celery's default prefork pool doesn't work there;
concurrency within a stage still comes from the ThreadPoolExecutor inside each supervisor,
see agents/data/supervisor.py).
"""
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402

flask_app = create_app()

celery = Celery(
    flask_app.import_name,
    broker=flask_app.config["CELERY_BROKER_URL"],
    backend=flask_app.config["CELERY_RESULT_BACKEND"],
)
celery.conf.update(
    task_track_started=True,
    worker_max_tasks_per_child=50,
    # Fail fast if Redis isn't reachable (e.g. not started yet) instead of the API request
    # that calls .delay() hanging on the default socket timeout.
    broker_transport_options={"socket_connect_timeout": 3, "socket_timeout": 3},
    broker_connection_timeout=3,
)


class _ContextTask(celery.Task):
    def __call__(self, *args, **kwargs):
        with flask_app.app_context():
            return self.run(*args, **kwargs)


celery.Task = _ContextTask

# Registers the @celery.task-decorated functions on import.
from app.workers import tasks  # noqa: E402,F401

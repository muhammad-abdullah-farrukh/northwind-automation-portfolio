from celery import Celery, signals

from app.core.config import get_settings
from app.core.logging import setup_logging

settings = get_settings()

celery_app = Celery("opscore", broker=settings.redis_url, backend=settings.redis_url, include=["app.workers.tasks"])
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,  # a worker killed mid-job hands the job back instead of losing it
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    broker_connection_retry_on_startup=True,
)


@signals.setup_logging.connect
def _json_logs(**_):
    """Same structured JSON logs as the API (job_id rides along via contextvars)."""
    setup_logging()

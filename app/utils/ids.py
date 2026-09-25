import uuid


def new_id(prefix: str = "") -> str:
    """uuid4 hex id, optionally prefixed (e.g. 'doc_', 'job_') for readability in logs/URLs."""
    raw = uuid.uuid4().hex
    return f"{prefix}{raw}" if prefix else raw

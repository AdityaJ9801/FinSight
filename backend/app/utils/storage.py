"""Local-filesystem object storage. Same interface an S3/MinIO-backed implementation would
expose, so swapping backends later is a one-file change (design doc §6: "Object storage").
"""
from __future__ import annotations

import shutil
from pathlib import Path

from flask import current_app


def _root() -> Path:
    root = Path(current_app.config["STORAGE_ROOT"])
    root.mkdir(parents=True, exist_ok=True)
    return root


def put_file(relative_path: str, src_path: str) -> str:
    """Copy src_path into storage at relative_path. Returns a uri-like string ('file://<relative_path>')."""
    dest = _root() / relative_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_path, dest)
    return f"file://{relative_path}"


def write_bytes(relative_path: str, data: bytes) -> str:
    dest = _root() / relative_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return f"file://{relative_path}"


def write_text(relative_path: str, text: str, encoding: str = "utf-8") -> str:
    dest = _root() / relative_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding=encoding)
    return f"file://{relative_path}"


def resolve(uri: str) -> Path:
    """uri like 'file://job_123/raw/x.xlsx' -> absolute Path."""
    if uri.startswith("file://"):
        uri = uri[len("file://"):]
    return _root() / uri


def read_bytes(uri: str) -> bytes:
    return resolve(uri).read_bytes()


def delete_dir(relative_path: str) -> None:
    """Removes a whole job's on-disk tree (every job's files live under its own
    <job_id>/... prefix -- see the write_* calls throughout the agents). Silently a no-op
    if it's already gone, so callers don't need their own existence check first."""
    target = (_root() / relative_path).resolve()
    root = _root().resolve()
    if root not in target.parents:
        raise ValueError(f"refusing to delete outside storage root: {relative_path}")
    shutil.rmtree(target, ignore_errors=True)

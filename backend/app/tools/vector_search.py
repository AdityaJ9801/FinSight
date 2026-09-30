"""Vector search over document chunks -- the pgvector stand-in (design doc §6.2/§6.9). Uses
the LLM gateway's /embeddings when LLM_EMBEDDINGS_ENABLED=true, otherwise a deterministic
local HashingVectorizer so RAG works even before a real embeddings endpoint exists. Cosine
similarity is computed in Python since SQLite has no native vector index at this scale.
"""
from __future__ import annotations

import re

import numpy as np
from flask import current_app

from app.extensions import db
from app.models.chunk import DocChunk
from app.tools.registry import tool

_HASHING_DIM = 256


def _fallback_embed(texts: list[str]) -> list[list[float]]:
    from sklearn.feature_extraction.text import HashingVectorizer

    vectorizer = HashingVectorizer(n_features=_HASHING_DIM, alternate_sign=False, norm="l2")
    matrix = vectorizer.transform(texts)
    return matrix.toarray().tolist()


def embed_texts(texts: list[str]) -> list[list[float]]:
    from app.llm_gateway import get_llm_gateway

    if current_app.config.get("LLM_EMBEDDINGS_ENABLED"):
        try:
            return get_llm_gateway().embed(texts)
        except NotImplementedError:
            pass
    return _fallback_embed(texts)


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


def index_document(tenant_id: str, document_id: str, text: str, page: int | None = None) -> int:
    pieces = chunk_text(text)
    if not pieces:
        return 0
    vectors = embed_texts(pieces)
    for i, (piece, vec) in enumerate(zip(pieces, vectors)):
        db.session.add(DocChunk(
            tenant_id=tenant_id, document_id=document_id, chunk_index=i,
            text=piece, page=page, embedding=vec,
        ))
    db.session.commit()
    return len(pieces)


def _cosine(a: list[float], b: list[float]) -> float:
    a_arr, b_arr = np.array(a), np.array(b)
    denom = (np.linalg.norm(a_arr) * np.linalg.norm(b_arr))
    return float(np.dot(a_arr, b_arr) / denom) if denom else 0.0


def search(tenant_id: str, query: str, top_k: int = 5,
           document_id: str | None = None, document_ids: list[str] | None = None) -> list[dict]:
    q = db.session.query(DocChunk).filter(DocChunk.tenant_id == tenant_id)
    if document_id:
        q = q.filter(DocChunk.document_id == document_id)
    elif document_ids is not None:
        # Scopes a search to one job's documents. Without this, a tenant with multiple
        # jobs would leak chunks from unrelated jobs into a QA answer for this one.
        q = q.filter(DocChunk.document_id.in_(document_ids)) if document_ids else q.filter(False)
    chunks = q.all()
    if not chunks:
        return []

    query_vec = embed_texts([query])[0]
    scored = [(c, _cosine(query_vec, c.embedding)) for c in chunks if c.embedding]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [
        {"id": c.id, "document_id": c.document_id, "page": c.page, "text": c.text, "score": score}
        for c, score in scored[:top_k]
    ]


tool("vector.search", allowed_agents=["schema_mapper", "qa"])(search)

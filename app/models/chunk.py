from app.extensions import db
from app.utils.ids import new_id


class DocChunk(db.Model):
    """Text chunks + embeddings for the QA agent's document RAG path (pgvector stand-in, §6.2/§6.9)."""

    __tablename__ = "doc_chunks"

    id = db.Column(db.String(36), primary_key=True, default=lambda: new_id("chk_"))
    tenant_id = db.Column(db.String(36), db.ForeignKey("tenants.id"), nullable=False, index=True)
    document_id = db.Column(db.String(36), db.ForeignKey("documents.id"), nullable=False, index=True)
    chunk_index = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False)
    page = db.Column(db.Integer, nullable=True)
    embedding = db.Column(db.JSON, nullable=True)  # list[float]

from datetime import datetime, timezone

from app.extensions import db
from app.utils.ids import new_id

JOB_STAGES = ("data", "analysis", "delivery", "done", "failed")
JOB_STATUSES = (
    "CREATED", "INGESTING", "MAPPING", "RECONCILING", "AWAITING_REVIEW", "DATA_VALIDATED",
    "ANALYZING", "PARTIAL", "SYNTHESIZING", "VERIFYING", "NEEDS_ANALYST", "RENDERING",
    "COMPLETED", "FAILED",
)


class Job(db.Model):
    """Serializes JobState (design doc §4.3): the blackboard every agent/stage reads and writes."""

    __tablename__ = "jobs"

    id = db.Column(db.String(36), primary_key=True, default=lambda: new_id("job_"))
    tenant_id = db.Column(db.String(36), db.ForeignKey("tenants.id"), nullable=False, index=True)
    entity_id = db.Column(db.String(36), db.ForeignKey("entities.id"), nullable=True, index=True)
    created_by = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)

    goal = db.Column(db.Text, nullable=False)
    plan_template = db.Column(db.String(60), default="full_analysis")

    stage = db.Column(db.String(20), default="data")
    status = db.Column(db.String(20), default="CREATED")

    # Not a DB-enforced ForeignKey: dataset_versions.job_id already references jobs.id, and
    # SQLite can't cleanly support a two-table FK cycle (no ALTER TABLE ADD CONSTRAINT).
    # This is a soft "current dataset version" pointer, kept in sync by the orchestrator.
    dataset_version_id = db.Column(db.String(36), nullable=True)
    open_reviews = db.Column(db.JSON, default=list)
    budget_spent = db.Column(db.JSON, default=dict)
    replans = db.Column(db.Integer, default=0)
    error = db.Column(db.Text, nullable=True)

    progress_pct = db.Column(db.Integer, default=0)
    progress_message = db.Column(db.String(255), default="Job created")

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    def set_progress(self, pct: int, message: str) -> None:
        self.progress_pct = pct
        self.progress_message = message
        self.updated_at = datetime.now(timezone.utc)


class TaskRun(db.Model):
    """Per-agent-task trace + idempotency cache (task_key = hash(agent, inputs, params, prompt_version), §6.10)."""

    __tablename__ = "task_runs"

    id = db.Column(db.String(36), primary_key=True, default=lambda: new_id("tr_"))
    job_id = db.Column(db.String(36), db.ForeignKey("jobs.id"), nullable=False, index=True)
    task_key = db.Column(db.String(64), nullable=False, index=True)  # sha256 hex
    agent = db.Column(db.String(60), nullable=False)
    status = db.Column(db.String(20), default="done")  # done|partial|failed|needs_review
    summary = db.Column(db.Text, nullable=True)
    outputs = db.Column(db.JSON, default=list)
    issues = db.Column(db.JSON, default=list)
    confidence = db.Column(db.Float, default=1.0)
    usage = db.Column(db.JSON, default=dict)
    attempt = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.UniqueConstraint("job_id", "task_key", name="uq_taskrun_job_key"),)


class JobInstruction(db.Model):
    """Extra guidance/data a user provides while a job is running (not the pre-run goal,
    not post-completion QA) -- picked up by the orchestrator at the next stage boundary
    (see orchestrator.apply_pending_instructions) and relayed into that stage's agent
    prompts if relevant, per §4.3's JobState-as-blackboard pattern: the orchestrator and
    agents don't message each other directly, they coordinate through state on the job."""

    __tablename__ = "job_instructions"

    id = db.Column(db.String(36), primary_key=True, default=lambda: new_id("instr_"))
    job_id = db.Column(db.String(36), db.ForeignKey("jobs.id"), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="pending")  # pending | applied | ignored
    stage_applied = db.Column(db.String(20), nullable=True)  # data | analysis | delivery
    target_agents = db.Column(db.JSON, default=list)
    orchestrator_note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    applied_at = db.Column(db.DateTime, nullable=True)

"""Agent contracts, ported from the design doc §4.2/§3.3. Every agent consumes a TaskSpec
and returns an AgentResult holding artifact handles, not raw data, so an agent's context
stays bounded no matter how large the underlying dataset is (design doc principle 2).
"""
from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Type, TypeVar

from pydantic import BaseModel, Field

from app.llm_gateway.base import LLMGateway
from app.tools.registry import registry as tool_registry

T = TypeVar("T", bound=BaseModel)


class ArtifactRef(BaseModel):
    id: str
    kind: str  # raw_file | table | dataset | metric_set | chart | report | text
    uri: str
    schema_summary: str | None = None
    row_count: int | None = None


class Budget(BaseModel):
    max_input_tokens: int = 30_000
    max_output_tokens: int = 4_000
    max_tool_calls: int = 20
    timeout_s: int = 300


class TaskSpec(BaseModel):
    task_id: str
    job_id: str
    tenant_id: str
    agent: str
    goal: str
    inputs: list[ArtifactRef] = Field(default_factory=list)
    params: dict = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    budget: Budget = Field(default_factory=Budget)
    attempt: int = 1
    prompt_version: str = "v1"


class Status(str, Enum):
    DONE = "done"
    PARTIAL = "partial"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class Issue(BaseModel):
    severity: str = "info"  # info | warn | error
    code: str
    message: str
    ref: str | None = None


class AgentResult(BaseModel):
    task_id: str
    status: Status
    outputs: list[ArtifactRef] = Field(default_factory=list)
    summary: str = Field(default="", max_length=3000)
    confidence: float = 1.0
    issues: list[Issue] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)


def task_key(agent: str, inputs: list[ArtifactRef], params: dict, prompt_version: str) -> str:
    payload = json.dumps({
        "agent": agent,
        "inputs": sorted([i.id for i in inputs]),
        "params": params,
        "prompt_version": prompt_version,
    }, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class BaseAgent:
    name: str = "base_agent"
    allowed_tools: list[str] = []
    prompt_version: str = "v1"

    def __init__(self, llm: LLMGateway):
        self.llm = llm

    def run(self, spec: TaskSpec) -> AgentResult:
        raise NotImplementedError

    def call_tool(self, tool_name: str, **kwargs):
        if self.allowed_tools and tool_name not in self.allowed_tools:
            raise PermissionError(f"{self.name} is not allowed to call tool '{tool_name}'")
        result, _elapsed = tool_registry.invoke(self.name, tool_name, **kwargs)
        return result

    def call_llm(
        self,
        messages: list[dict],
        schema: Type[T] | None = None,
        mask_pii: bool = False,
        tier: str = "default",
    ):
        """mask_pii defaults to False: most agents send internally-generated structured
        JSON (metric ids/codes/values via prompt_utils.embed_json), and PII masking's
        regexes -- BANK_ACCT in particular matches any bare 9-18 digit run -- would corrupt
        that JSON by replacing numeric values with [[BANK_ACCT_n]] tokens, breaking the
        json.loads round-trip on the other end. Pass mask_pii=True only where the message
        actually contains raw excerpted document text (e.g. IntakeAgent's classification
        prompt), which is the real PII exposure the design doc's §9 masking is for.

        tier="reasoning" routes to the gateway's reasoning-tier model (see design doc §7
        model tiering) for agents whose output quality matters most -- report writing,
        insight synthesis, verification -- while classification/extraction agents keep the
        default (faster/cheaper) model."""
        if mask_pii:
            from app.utils.pii import mask

            masked_messages = []
            for m in messages:
                result = mask(m.get("content", ""))
                masked_messages.append({**m, "content": result.masked_text})
            messages = masked_messages
        return self.llm.complete(messages, schema=schema, tier=tier)


class WorkerAgent(BaseAgent):
    def execute(self, spec: TaskSpec) -> AgentResult:
        raise NotImplementedError

    def run(self, spec: TaskSpec) -> AgentResult:
        result = self.execute(spec)
        self._record_task_run(spec, result)
        return result

    def _record_task_run(self, spec: TaskSpec, result: AgentResult) -> None:
        """Best-effort per-task trace for the /api/jobs/<id>/tasks debug endpoint (design
        doc §6.10 task_key). Never lets a logging failure break the actual agent result."""
        try:
            from app.extensions import db
            from app.models.job import TaskRun

            key = task_key(self.name, spec.inputs, spec.params, spec.prompt_version)
            db.session.add(TaskRun(
                job_id=spec.job_id, task_key=key, agent=self.name, status=result.status.value,
                summary=result.summary, outputs=[o.model_dump() for o in result.outputs],
                issues=[i.model_dump() for i in result.issues], confidence=result.confidence,
                usage=result.usage, attempt=spec.attempt,
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()


class SupervisorAgent(BaseAgent):
    def plan_subtasks(self, spec: TaskSpec) -> list[TaskSpec]:
        raise NotImplementedError

    def merge(self, results: list[AgentResult]) -> AgentResult:
        raise NotImplementedError

    def check_gate(self, results: list[AgentResult]) -> bool:
        raise NotImplementedError

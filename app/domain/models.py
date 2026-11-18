from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvestigationStatus(StrEnum):
    queued = "queued"
    running = "running"
    awaiting_approval = "awaiting_approval"
    completed = "completed"
    failed = "failed"


class FindingClassification(StrEnum):
    confirmed = "confirmed"
    probable = "probable"
    possible = "possible"
    unverified = "unverified"
    contradicted = "contradicted"


class InvestigationTask(StrictModel):
    id: str
    title: str
    status: str = "pending"


class InvestigationPlan(StrictModel):
    objective: str
    tasks: list[InvestigationTask]
    max_steps: int = Field(default=8, ge=1, le=20)


class EvidenceReference(StrictModel):
    evidence_id: str


class RetrievedEvidence(StrictModel):
    evidence_id: str
    source_id: str
    document_id: str
    chunk_id: str
    excerpt: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    sparse_score: float = 0.0
    dense_score: float | None = None
    retrieval_score: float = 0.0
    retrieved_at: datetime


class Hypothesis(StrictModel):
    id: str
    statement: str
    classification: FindingClassification
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    rationale: str


class Finding(StrictModel):
    id: str
    statement: str
    classification: FindingClassification
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)


class UnresolvedQuestion(StrictModel):
    question: str
    reason: str


class EvidenceConflict(StrictModel):
    description: str
    evidence_refs: list[EvidenceReference]


class ToolExecution(StrictModel):
    id: str
    tool_name: str
    status: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime
    completed_at: datetime
    simulated: bool = True


class ApprovalRequest(StrictModel):
    id: UUID
    investigation_id: UUID
    action: str
    rationale: str
    status: str = "pending"
    requested_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None
    decision_note: str | None = None


class InvestigationReport(StrictModel):
    summary: str
    findings: list[Finding]
    hypotheses: list[Hypothesis]
    unresolved_questions: list[UnresolvedQuestion]
    evidence: list[RetrievedEvidence]
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    recommended_actions: list[str]
    limitations: list[str]
    generated_at: datetime


class ExecutionMetadata(StrictModel):
    workflow_version: str = "1"
    completed_steps: int = 0
    warnings: list[str] = Field(default_factory=list)
    retrieval_mode: str | None = None
    started_at: datetime
    updated_at: datetime


class Investigation(StrictModel):
    id: UUID
    organization_id: str
    request: str
    simulation_scenario_id: str | None = None
    status: InvestigationStatus
    plan: InvestigationPlan | None = None
    evidence: list[RetrievedEvidence] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    unresolved_questions: list[UnresolvedQuestion] = Field(default_factory=list)
    tool_executions: list[ToolExecution] = Field(default_factory=list)
    approvals: list[ApprovalRequest] = Field(default_factory=list)
    report: InvestigationReport | None = None
    execution_metadata: ExecutionMetadata | None = None
    created_at: datetime
    updated_at: datetime


class InvestigationCreate(StrictModel):
    request: str = Field(min_length=8, max_length=10_000)
    simulation_scenario_id: str | None = Field(
        default=None, pattern=r"^INC-\d{3}$"
    )


class SimulationRunCreate(StrictModel):
    scenario_id: str = Field(pattern=r"^INC-\d{3}$")


class ApprovalDecisionRequest(StrictModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    note: str | None = Field(default=None, max_length=2000)


class ApprovalCreateRequest(StrictModel):
    action: str = Field(min_length=8, max_length=2000)
    rationale: str = Field(min_length=8, max_length=4000)


class IngestionResponse(StrictModel):
    document_id: str
    source: str
    version: int = Field(ge=1)
    chunk_count: int
    content_hash: str


class DocumentStatusResponse(StrictModel):
    document_id: str
    source: str
    status: str
    version: int = Field(ge=1)
    chunk_count: int = Field(ge=0)
    content_hash: str
    created_at: datetime


class KnowledgeSearchResponse(StrictModel):
    evidence: list[RetrievedEvidence]
    retrieval_mode: str
    warnings: list[str] = Field(default_factory=list)


class SyntheticScenarioSummary(StrictModel):
    scenario_id: str
    title: str
    description: str
    difficulty: str
    severity: str
    affected_services: list[str]
    synthetic: bool = True


class InvestigationEvent(StrictModel):
    id: int
    investigation_id: UUID
    event_type: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

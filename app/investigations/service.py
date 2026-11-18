import logging
import threading
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import (
    ApprovalRequest,
    Investigation,
    InvestigationEvent,
    InvestigationStatus,
    ToolExecution,
)
from app.investigations.graph import build_investigation_graph
from app.persistence.database import (
    ApprovalRecord,
    AuditEventRecord,
    InvestigationEventRecord,
    InvestigationRecord,
    OrganizationRecord,
    ToolExecutionRecord,
    get_session_factory,
    normalize_db_datetime,
    utc_now,
)
from app.persistence.checkpoints import persistent_checkpointer

logger = logging.getLogger(__name__)
_RUNNING_LOCK = threading.Lock()
_RUNNING_INVESTIGATIONS: set[str] = set()


class InvestigationNotFound(LookupError):
    pass


def _event(
    session: Session,
    organization_id: str,
    investigation_id: str,
    event_type: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> None:
    session.add(
        InvestigationEventRecord(
            organization_id=organization_id,
            investigation_id=investigation_id,
            event_type=event_type,
            message=message,
            data=data or {},
        )
    )


def _to_approval(record: ApprovalRecord) -> ApprovalRequest:
    return ApprovalRequest(
        id=UUID(record.id),
        investigation_id=UUID(record.investigation_id),
        action=record.action,
        rationale=record.rationale,
        status=record.status,
        requested_at=normalize_db_datetime(record.requested_at),
        decided_at=(
            normalize_db_datetime(record.decided_at) if record.decided_at else None
        ),
        decided_by=record.decided_by,
        decision_note=record.decision_note,
    )


def _to_investigation(
    record: InvestigationRecord, approvals: list[ApprovalRecord] | None = None
) -> Investigation:
    payload: dict[str, Any] = {
        "id": UUID(record.id),
        "organization_id": record.organization_id,
        "request": record.request,
        "status": record.status,
        "plan": record.plan,
        "evidence": record.evidence or [],
        "hypotheses": record.hypotheses or [],
        "findings": record.findings or [],
        "unresolved_questions": record.unresolved_questions or [],
        "tool_executions": record.tool_executions or [],
        "approvals": [_to_approval(approval).model_dump(mode="json") for approval in approvals or []],
        "report": record.report,
        "execution_metadata": record.execution_metadata,
        "created_at": normalize_db_datetime(record.created_at),
        "updated_at": normalize_db_datetime(record.updated_at),
    }
    return Investigation.model_validate(payload)


def create_investigation(
    session: Session, request: str, organization_id: str = "local"
) -> Investigation:
    if session.get(OrganizationRecord, organization_id) is None:
        session.add(OrganizationRecord(id=organization_id, name=organization_id))
        session.flush()
    now = utc_now()
    record = InvestigationRecord(
        id=str(uuid4()),
        organization_id=organization_id,
        request=request,
        status=InvestigationStatus.queued.value,
        evidence=[],
        hypotheses=[],
        findings=[],
        unresolved_questions=[],
        tool_executions=[],
        execution_metadata={
            "workflow_version": "1",
            "completed_steps": 0,
            "warnings": [],
            "started_at": now.isoformat(),
            "updated_at": now.isoformat(),
        },
        state_json={"request": request},
    )
    session.add(record)
    _event(session, organization_id, record.id, "queued", "Investigation queued.")
    session.add(
        AuditEventRecord(
            organization_id=organization_id,
            action="investigation.created",
            resource_id=record.id,
            details={},
        )
    )
    session.commit()
    session.refresh(record)
    return _to_investigation(record)


def run_investigation(investigation_id: str, organization_id: str = "local") -> None:
    with _RUNNING_LOCK:
        if investigation_id in _RUNNING_INVESTIGATIONS:
            return
        _RUNNING_INVESTIGATIONS.add(investigation_id)
    try:
        _run_investigation(investigation_id, organization_id)
    finally:
        with _RUNNING_LOCK:
            _RUNNING_INVESTIGATIONS.discard(investigation_id)


def _run_investigation(investigation_id: str, organization_id: str) -> None:
    factory = get_session_factory()
    with factory() as session:
        record = session.scalar(
            select(InvestigationRecord).where(
                InvestigationRecord.id == investigation_id,
                InvestigationRecord.organization_id == organization_id,
            )
        )
        if record is None or record.status == InvestigationStatus.completed.value:
            return
        started = utc_now()
        record.status = InvestigationStatus.running.value
        state: dict[str, Any] = {
            "investigation_id": record.id,
            "organization_id": organization_id,
            "request": record.request,
            "evidence": [],
            "hypotheses": [],
            "findings": [],
            "unresolved_questions": [],
            "tool_executions": [],
            "warnings": [],
        }
        _event(session, organization_id, record.id, "started", "Investigation workflow started.")
        session.commit()

    try:
        with persistent_checkpointer() as checkpointer:
            graph = build_investigation_graph(checkpointer)
            config = {
                "configurable": {"thread_id": investigation_id},
                "recursion_limit": 12,
            }
            for update in graph.stream(state, config=config, stream_mode="updates"):
                node_name, node_data = next(iter(update.items()))
                state.update(node_data)
                with factory() as session:
                    record = session.scalar(
                        select(InvestigationRecord).where(
                            InvestigationRecord.id == investigation_id,
                            InvestigationRecord.organization_id == organization_id,
                        )
                    )
                    if record is None:
                        raise InvestigationNotFound(investigation_id)
                    record.state_json = state
                    record.plan = state.get("plan")
                    record.evidence = state.get("evidence", [])
                    record.hypotheses = state.get("hypotheses", [])
                    record.findings = state.get("findings", [])
                    record.unresolved_questions = state.get("unresolved_questions", [])
                    record.tool_executions = state.get("tool_executions", [])
                    if node_name == "tools":
                        for raw_execution in record.tool_executions:
                            execution = ToolExecution.model_validate(raw_execution)
                            session.merge(
                                ToolExecutionRecord(
                                    id=execution.id,
                                    organization_id=organization_id,
                                    investigation_id=record.id,
                                    tool_name=execution.tool_name,
                                    status=execution.status,
                                    input_json=execution.input,
                                    output_json=execution.output,
                                    simulated=execution.simulated,
                                    started_at=execution.started_at,
                                    completed_at=execution.completed_at,
                                )
                            )
                    record.execution_metadata = {
                        "workflow_version": "1",
                        "completed_steps": int(
                            (record.execution_metadata or {}).get("completed_steps", 0)
                        )
                        + 1,
                        "warnings": state.get("warnings", []),
                        "started_at": started.isoformat(),
                        "updated_at": utc_now().isoformat(),
                        "retrieval_mode": state.get("retrieval_mode", "pending"),
                    }
                    if node_name == "report":
                        record.report = state.get("report")
                        record.status = InvestigationStatus.completed.value
                    _event(
                        session,
                        organization_id,
                        record.id,
                        node_name,
                        f"Completed {node_name} step.",
                        {"step": node_name},
                    )
                    if node_name == "report":
                        session.add(
                            AuditEventRecord(
                                organization_id=organization_id,
                                action="investigation.completed",
                                resource_id=record.id,
                                details={
                                    "evidence_count": len(record.evidence or []),
                                    "finding_count": len(record.findings or []),
                                },
                            )
                        )
                    session.commit()
            checkpoint_state = graph.get_state(config).values
            if checkpoint_state.get("report"):
                with factory() as session:
                    record = session.scalar(
                        select(InvestigationRecord).where(
                            InvestigationRecord.id == investigation_id,
                            InvestigationRecord.organization_id == organization_id,
                        )
                    )
                    if record:
                        record.state_json = checkpoint_state
                        record.report = checkpoint_state["report"]
                        record.status = InvestigationStatus.completed.value
                        record.updated_at = utc_now()
                        session.commit()
    except Exception as exc:
        logger.exception("Investigation %s failed", investigation_id)
        with factory() as session:
            record = session.scalar(
                select(InvestigationRecord).where(
                    InvestigationRecord.id == investigation_id,
                    InvestigationRecord.organization_id == organization_id,
                )
            )
            if record:
                record.status = InvestigationStatus.failed.value
                metadata = dict(record.execution_metadata or {})
                metadata["warnings"] = list(metadata.get("warnings", [])) + [
                    f"Workflow failed ({type(exc).__name__})."
                ]
                metadata["updated_at"] = utc_now().isoformat()
                record.execution_metadata = metadata
                _event(
                    session,
                    organization_id,
                    record.id,
                    "failed",
                    "Investigation workflow failed; inspect backend logs.",
                    {"error_type": type(exc).__name__},
                )
                session.add(
                    AuditEventRecord(
                        organization_id=organization_id,
                        action="investigation.failed",
                        resource_id=record.id,
                        details={"error_type": type(exc).__name__},
                    )
                )
                session.commit()


def get_investigation(
    session: Session, investigation_id: str, organization_id: str = "local"
) -> Investigation:
    record = session.scalar(
        select(InvestigationRecord).where(
            InvestigationRecord.id == investigation_id,
            InvestigationRecord.organization_id == organization_id,
        )
    )
    if record is None:
        raise InvestigationNotFound(investigation_id)
    approvals = session.scalars(
        select(ApprovalRecord).where(
            ApprovalRecord.investigation_id == investigation_id,
            ApprovalRecord.organization_id == organization_id,
        )
    ).all()
    return _to_investigation(record, list(approvals))


def list_investigations(
    session: Session, organization_id: str = "local", limit: int = 50
) -> list[Investigation]:
    records = session.scalars(
        select(InvestigationRecord)
        .where(InvestigationRecord.organization_id == organization_id)
        .order_by(InvestigationRecord.created_at.desc())
        .limit(limit)
    ).all()
    return [_to_investigation(record) for record in records]


def get_events(
    session: Session, investigation_id: str, organization_id: str = "local"
) -> list[InvestigationEvent]:
    if session.scalar(
        select(InvestigationRecord.id).where(
            InvestigationRecord.id == investigation_id,
            InvestigationRecord.organization_id == organization_id,
        )
    ) is None:
        raise InvestigationNotFound(investigation_id)
    records = session.scalars(
        select(InvestigationEventRecord)
        .where(
            InvestigationEventRecord.investigation_id == investigation_id,
            InvestigationEventRecord.organization_id == organization_id,
        )
        .order_by(InvestigationEventRecord.id)
    ).all()
    return [
        InvestigationEvent(
            id=item.id,
            investigation_id=UUID(item.investigation_id),
            event_type=item.event_type,
            message=item.message,
            data=item.data or {},
            created_at=normalize_db_datetime(item.created_at),
        )
        for item in records
    ]


def create_approval(
    session: Session,
    investigation_id: str,
    organization_id: str,
    action: str,
    rationale: str,
) -> ApprovalRequest:
    if session.scalar(
        select(InvestigationRecord.id).where(
            InvestigationRecord.id == investigation_id,
            InvestigationRecord.organization_id == organization_id,
        )
    ) is None:
        raise InvestigationNotFound(investigation_id)
    record = ApprovalRecord(
        id=str(uuid4()),
        organization_id=organization_id,
        investigation_id=investigation_id,
        action=action,
        rationale=rationale,
    )
    session.add(record)
    _event(
        session,
        organization_id,
        investigation_id,
        "approval_requested",
        "Approval requested for a proposed action.",
        {"approval_id": record.id},
    )
    session.add(
        AuditEventRecord(
            organization_id=organization_id,
            action="approval.requested",
            resource_id=record.id,
            details={"investigation_id": investigation_id},
        )
    )
    session.commit()
    session.refresh(record)
    return _to_approval(record)


def decide_approval(
    session: Session,
    approval_id: str,
    organization_id: str,
    decision: str,
    note: str | None,
    actor: str = "local",
) -> ApprovalRequest:
    record = session.scalar(
        select(ApprovalRecord).where(
            ApprovalRecord.id == approval_id,
            ApprovalRecord.organization_id == organization_id,
        )
    )
    if record is None:
        raise InvestigationNotFound(approval_id)
    if record.status != "pending":
        raise ValueError(f"approval is already {record.status}")
    record.status = decision
    record.decided_at = datetime.now(timezone.utc)
    record.decided_by = actor
    record.decision_note = note
    _event(
        session,
        organization_id,
        record.investigation_id,
        "approval_decided",
        f"Approval was {decision}.",
        {"approval_id": approval_id},
    )
    session.add(
        AuditEventRecord(
            organization_id=organization_id,
            actor=actor,
            action=f"approval.{decision}",
            resource_id=approval_id,
            details={"investigation_id": record.investigation_id},
        )
    )
    session.commit()
    session.refresh(record)
    return _to_approval(record)


def pending_approvals(
    session: Session, organization_id: str = "local", limit: int = 100
) -> list[ApprovalRequest]:
    records = session.scalars(
        select(ApprovalRecord)
        .where(
            ApprovalRecord.organization_id == organization_id,
            ApprovalRecord.status == "pending",
        )
        .order_by(ApprovalRecord.requested_at.desc())
        .limit(limit)
    ).all()
    return [_to_approval(record) for record in records]


def resume_interrupted_investigations() -> None:
    factory = get_session_factory()
    with factory() as session:
        ids = session.execute(
            select(InvestigationRecord.id, InvestigationRecord.organization_id).where(
                InvestigationRecord.status.in_(
                    [InvestigationStatus.queued.value, InvestigationStatus.running.value]
                )
            )
        ).all()
    for investigation_id, organization_id in ids:
        run_investigation(investigation_id, organization_id)


def log_tool_executions(
    session: Session, investigation: Investigation
) -> None:
    for execution in investigation.tool_executions:
        session.merge(
            ToolExecutionRecord(
                id=execution.id,
                organization_id=investigation.organization_id,
                investigation_id=str(investigation.id),
                tool_name=execution.tool_name,
                status=execution.status,
                input_json=execution.input,
                output_json=execution.output,
                simulated=execution.simulated,
                started_at=execution.started_at,
                completed_at=execution.completed_at,
            )
        )

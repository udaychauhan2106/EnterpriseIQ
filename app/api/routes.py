import asyncio
import hashlib
import json
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import AsyncIterator, Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.domain.models import (
    ApprovalCreateRequest,
    ApprovalDecisionRequest,
    ApprovalRequest,
    DocumentStatusResponse,
    IngestionResponse,
    Investigation,
    InvestigationCreate,
    InvestigationEvent,
    KnowledgeSearchResponse,
    SimulationRunCreate,
    SyntheticScenarioSummary,
)
from app.ingestion.chunking.document import chunk_document_text
from app.ingestion.loaders.html import parse_html
from app.ingestion.loaders.office import parse_office
from app.ingestion.loaders.pdf import parse_pdf
from app.investigations.service import (
    InvestigationNotFound,
    create_approval,
    create_investigation,
    decide_approval,
    get_events,
    get_investigation,
    list_investigations,
    pending_approvals,
    run_investigation,
)
from app.persistence.database import (
    DocumentChunkRecord,
    DocumentRecord,
    InvestigationRecord,
    OrganizationRecord,
    get_db_session,
    get_session_factory,
    utc_now,
)
from app.retrieval.hybrid import hybrid_search
from app.simulator.adapter import (
    deployment_history,
    incident_history,
    search_logs,
    service_health,
    read_scenario_artifact,
    scenario_evidence_manifest,
    structured_metrics,
)
from app.simulator.ingestion import ingest_scenario_evidence
from app.simulator.runs import SimulationRunNotFound, simulation_runs
from app.simulator.scenarios import SCENARIO_CATALOG, get_scenario

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")
_SUPPORTED_UPLOADS = {".pdf", ".docx", ".pptx", ".txt", ".md", ".html", ".htm", ".csv", ".json", ".log"}


def _organization_id(
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
) -> str:
    if settings.ENTERPRISEIQ_API_KEY:
        return settings.ENTERPRISEIQ_ORGANIZATION_ID
    return (x_organization_id or "local").strip()[:100] or "local"


def _require_scenario(scenario_id: str):
    try:
        return get_scenario(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Synthetic scenario not found.") from exc


def _parse_upload(filename: str, content: bytes) -> str:
    extension = Path(filename).suffix.lower()
    if extension in {".txt", ".md", ".csv", ".json", ".log"}:
        return content.decode("utf-8")
    handle = tempfile.NamedTemporaryFile(suffix=extension, delete=False)
    path = Path(handle.name)
    try:
        with handle:
            handle.write(content)
        if extension in {".html", ".htm"}:
            return parse_html(str(path))
        if extension == ".pdf":
            return parse_pdf(str(path))
        if extension in {".docx", ".pptx"}:
            if not zipfile.is_zipfile(path):
                raise ValueError("Office file is not a valid ZIP package.")
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                expanded_bytes = sum(entry.file_size for entry in entries)
                if len(entries) > 10_000:
                    raise ValueError("Office file contains too many archive entries.")
                if expanded_bytes > settings.ENTERPRISEIQ_MAX_EXPANDED_UPLOAD_BYTES:
                    raise ValueError("Office file exceeds the expanded-size limit.")
                if any(
                    entry.file_size / max(1, entry.compress_size) > 1000
                    for entry in entries
                ):
                    raise ValueError("Office file contains a suspicious compression ratio.")
        return parse_office(str(path))
    finally:
        path.unlink(missing_ok=True)


@router.get("/auth/status")
def auth_status() -> dict[str, bool]:
    return {"authentication_required": bool(settings.ENTERPRISEIQ_API_KEY)}


@router.post("/investigations", response_model=Investigation, status_code=202)
def start_investigation(
    request: InvestigationCreate,
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", max_length=128
    ),
    session: Session = Depends(get_db_session),
    organization_id: str = Depends(_organization_id),
) -> Investigation:
    if len(request.request) > settings.ENTERPRISEIQ_MAX_QUERY_CHARS:
        raise HTTPException(
            status_code=413,
            detail="Investigation request exceeds the configured character limit.",
        )
    request_fingerprint = hashlib.sha256(
        (
            request.request
            + "\n"
            + (request.simulation_scenario_id or "")
        ).encode("utf-8")
    ).hexdigest()
    if idempotency_key:
        existing = session.scalar(
            select(InvestigationRecord).where(
                InvestigationRecord.organization_id == organization_id,
                InvestigationRecord.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_fingerprint != request_fingerprint:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency key was already used for a different investigation.",
                )
            return get_investigation(session, existing.id, organization_id)
    try:
        if request.simulation_scenario_id:
            _require_scenario(request.simulation_scenario_id)
            ingest_scenario_evidence(
                session, organization_id, request.simulation_scenario_id
            )
        investigation = create_investigation(
            session,
            request.request,
            organization_id,
            request.simulation_scenario_id,
            idempotency_key,
            request_fingerprint if idempotency_key else None,
        )
    except IntegrityError:
        if not idempotency_key:
            raise
        session.rollback()
        existing = session.scalar(
            select(InvestigationRecord).where(
                InvestigationRecord.organization_id == organization_id,
                InvestigationRecord.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise HTTPException(
                status_code=409,
                detail="Investigation creation conflicted; retry with the same idempotency key.",
            )
        if existing.request_fingerprint != request_fingerprint:
            raise HTTPException(
                status_code=409,
                detail="Idempotency key was already used for a different investigation.",
            )
        return get_investigation(session, existing.id, organization_id)
    background_tasks.add_task(
        run_investigation, str(investigation.id), organization_id
    )
    return investigation


@router.get("/lab/scenarios", response_model=list[SyntheticScenarioSummary])
def lab_scenarios() -> list[SyntheticScenarioSummary]:
    severity_rank = {"debug": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}
    return [
        SyntheticScenarioSummary(
            scenario_id=package.scenario.scenario_id,
            title=package.scenario.title,
            description=package.scenario.description,
            difficulty=package.scenario.difficulty.value,
            severity=max(
                (event.severity.value for event in package.scenario.events),
                key=lambda value: severity_rank[value],
                default="info",
            ),
            affected_services=list(package.scenario.affected_services),
            synthetic=True,
        )
        for package in SCENARIO_CATALOG.values()
    ]


@router.get("/lab/scenarios/{scenario_id}/evidence")
def lab_scenario_evidence(scenario_id: str) -> dict:
    _require_scenario(scenario_id)
    sources = scenario_evidence_manifest(scenario_id)
    return {
        "scenario_id": scenario_id,
        "synthetic": True,
        "available": bool(sources) and all(source["available"] for source in sources),
        "sources": sources,
    }


@router.get("/lab/scenarios/{scenario_id}/artifacts/{artifact_id}")
def lab_scenario_artifact(scenario_id: str, artifact_id: str) -> dict:
    _require_scenario(scenario_id)
    try:
        return read_scenario_artifact(scenario_id, artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Synthetic evidence artifact not found.") from exc


@router.post("/lab/scenarios/{scenario_id}/publish", status_code=201)
def publish_scenario(
    scenario_id: str,
    session: Session = Depends(get_db_session),
    organization_id: str = Depends(_organization_id),
) -> dict:
    _require_scenario(scenario_id)
    result = ingest_scenario_evidence(session, organization_id, scenario_id)
    session.commit()
    return result


@router.get("/lab/scenarios/{scenario_id}/history")
def lab_scenario_history(
    scenario_id: str,
    q: str = Query(default="", max_length=1000),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    _require_scenario(scenario_id)
    return incident_history(scenario_id, q, limit)


@router.get("/lab/scenarios/{scenario_id}/logs")
def lab_scenario_logs(
    scenario_id: str,
    q: str = Query(default="", max_length=1000),
    log_type: Literal["application", "infrastructure", "monitoring"] = "application",
    service_id: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    _require_scenario(scenario_id)
    return search_logs(scenario_id, q, log_type, service_id, limit)


@router.get("/lab/scenarios/{scenario_id}/metrics")
def lab_scenario_metrics(
    scenario_id: str,
    q: str = Query(default="", max_length=1000),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    _require_scenario(scenario_id)
    return structured_metrics(scenario_id, q, limit)


@router.get("/lab/scenarios/{scenario_id}/deployments")
def lab_scenario_deployments(
    scenario_id: str,
    q: str = Query(default="", max_length=1000),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    _require_scenario(scenario_id)
    return deployment_history(scenario_id, q, limit)


@router.get("/lab/scenarios/{scenario_id}/health")
def lab_scenario_health(scenario_id: str) -> dict:
    _require_scenario(scenario_id)
    return service_health(scenario_id)


@router.get("/lab/runs")
def lab_runs() -> list[dict]:
    return simulation_runs.list()


@router.post("/lab/runs", status_code=201)
def start_lab_run(request: SimulationRunCreate) -> dict:
    _require_scenario(request.scenario_id)
    return simulation_runs.start(request.scenario_id)


@router.get("/lab/runs/{run_id}")
def lab_run(run_id: str) -> dict:
    try:
        return simulation_runs.get(run_id)
    except SimulationRunNotFound as exc:
        raise HTTPException(status_code=404, detail="Simulation run not found.") from exc


@router.post("/lab/runs/{run_id}/stop")
def stop_lab_run(run_id: str) -> dict:
    try:
        return simulation_runs.stop(run_id)
    except SimulationRunNotFound as exc:
        raise HTTPException(status_code=404, detail="Simulation run not found.") from exc


@router.post("/lab/runs/{run_id}/replay", status_code=201)
def replay_lab_run(run_id: str) -> dict:
    try:
        return simulation_runs.replay(run_id)
    except SimulationRunNotFound as exc:
        raise HTTPException(status_code=404, detail="Simulation run not found.") from exc


@router.post("/lab/runs/{run_id}/reset")
def reset_lab_run(run_id: str) -> dict[str, str | bool]:
    try:
        return simulation_runs.remove(run_id)
    except SimulationRunNotFound as exc:
        raise HTTPException(status_code=404, detail="Simulation run not found.") from exc


@router.post("/lab/reset")
def reset_lab() -> dict[str, int | bool]:
    return simulation_runs.reset()


@router.get("/investigations", response_model=list[Investigation])
def investigations(
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
    organization_id: str = Depends(_organization_id),
) -> list[Investigation]:
    return list_investigations(session, organization_id, limit)


@router.get("/investigations/{investigation_id}", response_model=Investigation)
def investigation_detail(
    investigation_id: str,
    session: Session = Depends(get_db_session),
    organization_id: str = Depends(_organization_id),
) -> Investigation:
    try:
        return get_investigation(session, investigation_id, organization_id)
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation not found.") from exc


@router.get(
    "/investigations/{investigation_id}/report",
)
def investigation_report(
    investigation_id: str,
    session: Session = Depends(get_db_session),
    organization_id: str = Depends(_organization_id),
) -> dict:
    try:
        investigation = get_investigation(session, investigation_id, organization_id)
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation not found.") from exc
    if investigation.report is None:
        raise HTTPException(status_code=202, detail="Investigation report is not ready.")
    return investigation.report.model_dump(mode="json")


@router.post("/investigations/{investigation_id}/resume", status_code=202)
def resume_investigation(
    investigation_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db_session),
    organization_id: str = Depends(_organization_id),
) -> dict[str, str]:
    try:
        investigation = get_investigation(session, investigation_id, organization_id)
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation not found.") from exc
    if investigation.status == "completed":
        raise HTTPException(status_code=409, detail="Investigation is already complete.")
    background_tasks.add_task(run_investigation, investigation_id, organization_id)
    return {"status": "queued", "investigation_id": investigation_id}


@router.get(
    "/investigations/{investigation_id}/events",
    response_model=list[InvestigationEvent],
)
def investigation_events(
    investigation_id: str,
    session: Session = Depends(get_db_session),
    organization_id: str = Depends(_organization_id),
) -> list[InvestigationEvent]:
    try:
        return get_events(session, investigation_id, organization_id)
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation not found.") from exc


@router.get("/investigations/{investigation_id}/events/stream")
async def stream_investigation_events(
    investigation_id: str,
    organization_id: str = Depends(_organization_id),
) -> StreamingResponse:
    factory = get_session_factory()
    with factory() as session:
        try:
            get_investigation(session, investigation_id, organization_id)
        except InvestigationNotFound as exc:
            raise HTTPException(status_code=404, detail="Investigation not found.") from exc

    async def event_stream() -> AsyncIterator[str]:
        last_id = 0
        for _ in range(120):
            with factory() as session:
                events = get_events(session, investigation_id, organization_id)
                current = get_investigation(session, investigation_id, organization_id)
            for event in events:
                if event.id <= last_id:
                    continue
                last_id = event.id
                payload = json.dumps(event.model_dump(mode="json"))
                yield f"id: {event.id}\nevent: update\ndata: {payload}\n\n"
            if current.status in {"completed", "failed"}:
                yield "event: close\ndata: {}\n\n"
                return
            await asyncio.sleep(1)
        yield "event: timeout\ndata: {}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/approvals", response_model=list[ApprovalRequest])
def approvals(
    session: Session = Depends(get_db_session),
    organization_id: str = Depends(_organization_id),
) -> list[ApprovalRequest]:
    return pending_approvals(session, organization_id)


@router.post(
    "/investigations/{investigation_id}/approvals",
    response_model=ApprovalRequest,
    status_code=201,
)
def request_approval(
    investigation_id: str,
    request: ApprovalCreateRequest,
    session: Session = Depends(get_db_session),
    organization_id: str = Depends(_organization_id),
) -> ApprovalRequest:
    try:
        return create_approval(
            session,
            investigation_id,
            organization_id,
            request.action,
            request.rationale,
        )
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation not found.") from exc


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalRequest)
def approval_decision(
    approval_id: str,
    request: ApprovalDecisionRequest,
    session: Session = Depends(get_db_session),
    organization_id: str = Depends(_organization_id),
) -> ApprovalRequest:
    try:
        return decide_approval(
            session,
            approval_id,
            organization_id,
            request.decision,
            request.note,
        )
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Approval not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/knowledge/documents", response_model=IngestionResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    session: Session = Depends(get_db_session),
    organization_id: str = Depends(_organization_id),
) -> IngestionResponse:
    filename = Path(file.filename or "").name
    extension = Path(filename).suffix.lower()
    if not filename or extension not in _SUPPORTED_UPLOADS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type. Supported extensions: {', '.join(sorted(_SUPPORTED_UPLOADS))}.",
        )
    content = await file.read(settings.ENTERPRISEIQ_MAX_UPLOAD_BYTES + 1)
    if len(content) > settings.ENTERPRISEIQ_MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Uploaded file exceeds the configured size limit.")
    if not content:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")
    try:
        text = _parse_upload(filename, content)
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="File content could not be decoded or parsed.") from exc
    except Exception as exc:
        logger.exception("Document parsing failed for %s", filename)
        raise HTTPException(status_code=422, detail="Document parsing failed.") from exc
    if not text.strip():
        raise HTTPException(status_code=422, detail="No text could be extracted from the document.")

    content_hash = hashlib.sha256(content).hexdigest()
    existing = session.scalar(
        select(DocumentRecord).where(
            DocumentRecord.organization_id == organization_id,
            DocumentRecord.content_hash == content_hash,
        )
    )
    if existing:
        count = session.query(DocumentChunkRecord).filter_by(document_id=existing.id).count()
        return IngestionResponse(
            document_id=existing.id,
            source=existing.source,
            version=existing.version,
            chunk_count=count,
            content_hash=content_hash,
        )
    if session.get(OrganizationRecord, organization_id) is None:
        session.add(OrganizationRecord(id=organization_id, name=organization_id))
        session.flush()
    document_id = hashlib.sha256(
        f"{organization_id}:{content_hash}".encode("utf-8")
    ).hexdigest()
    latest_version = session.scalar(
        select(func.max(DocumentRecord.version)).where(
            DocumentRecord.organization_id == organization_id,
            DocumentRecord.source == filename,
        )
    )
    version = (latest_version or 0) + 1
    chunks = chunk_document_text(text)
    session.add(
        DocumentRecord(
            id=document_id,
            organization_id=organization_id,
            source=filename,
            content_hash=content_hash,
            version=version,
            metadata_json={
                "extension": extension,
                "version": version,
                "source_type": "uploaded",
                "uploaded_at": utc_now().isoformat(),
            },
        )
    )
    for index, chunk in enumerate(chunks):
        chunk_id = hashlib.sha256(
            f"{document_id}:{index}".encode("utf-8")
        ).hexdigest()
        session.add(
            DocumentChunkRecord(
                id=chunk_id,
                organization_id=organization_id,
                document_id=document_id,
                chunk_index=index,
                text=chunk,
                metadata_json={
                    "source": filename,
                    "source_type": "uploaded",
                    "version": version,
                },
            )
        )
    session.commit()
    return IngestionResponse(
        document_id=document_id,
        source=filename,
        version=version,
        chunk_count=len(chunks),
        content_hash=content_hash,
    )


@router.get(
    "/knowledge/documents/{document_id}",
    response_model=DocumentStatusResponse,
)
def document_status(
    document_id: str,
    session: Session = Depends(get_db_session),
    organization_id: str = Depends(_organization_id),
) -> DocumentStatusResponse:
    document = session.scalar(
        select(DocumentRecord).where(
            DocumentRecord.id == document_id,
            DocumentRecord.organization_id == organization_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    count = session.query(DocumentChunkRecord).filter_by(document_id=document.id).count()
    return DocumentStatusResponse(
        document_id=document.id,
        source=document.source,
        status="indexed",
        version=document.version,
        chunk_count=count,
        content_hash=document.content_hash,
        created_at=document.created_at,
    )


@router.get("/knowledge/search", response_model=KnowledgeSearchResponse)
def knowledge_search(
    q: str = Query(min_length=1, max_length=10_000),
    limit: int = Query(default=8, ge=1, le=20),
    source_type: str | None = Query(default=None, max_length=100),
    simulation_scenario_id: str | None = Query(default=None, pattern=r"^INC-\d{3}$"),
    session: Session = Depends(get_db_session),
    organization_id: str = Depends(_organization_id),
) -> KnowledgeSearchResponse:
    if len(q) > settings.ENTERPRISEIQ_MAX_QUERY_CHARS:
        raise HTTPException(
            status_code=413,
            detail="Search query exceeds the configured character limit.",
        )
    if simulation_scenario_id:
        _require_scenario(simulation_scenario_id)
    result = hybrid_search(
        q,
        session,
        organization_id,
        limit=limit,
        source_type=source_type,
        simulation_scenario_id=simulation_scenario_id,
    )
    return KnowledgeSearchResponse(
        evidence=result.evidence,
        retrieval_mode=result.mode,
        warnings=result.warnings,
    )

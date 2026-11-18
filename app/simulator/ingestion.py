import hashlib
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ingestion.chunking.document import chunk_document_text
from app.persistence.database import (
    DocumentChunkRecord,
    DocumentRecord,
    OrganizationRecord,
    utc_now,
)
from app.simulator.adapter import publishable_artifacts


def ingest_scenario_evidence(
    session: Session, organization_id: str, scenario_id: str
) -> dict[str, Any]:
    if session.get(OrganizationRecord, organization_id) is None:
        session.add(OrganizationRecord(id=organization_id, name=organization_id))
        session.flush()

    documents: list[dict[str, Any]] = []
    total_chunks = 0
    for relative_path, text in publishable_artifacts(scenario_id):
        source = f"Nexora/{scenario_id}/{relative_path}"
        content = text.encode("utf-8")
        content_hash = hashlib.sha256(content).hexdigest()
        existing = session.scalar(
            select(DocumentRecord).where(
                DocumentRecord.organization_id == organization_id,
                DocumentRecord.content_hash == content_hash,
            )
        )
        if existing is not None:
            metadata = existing.metadata_json or {}
            if metadata.get("scenario_id") != scenario_id:
                raise ValueError(
                    "Synthetic evidence hash collides with a different document source."
                )
            chunk_count = session.query(DocumentChunkRecord).filter_by(
                document_id=existing.id
            ).count()
            documents.append(
                {
                    "document_id": existing.id,
                    "source": existing.source,
                    "chunk_count": chunk_count,
                }
            )
            total_chunks += chunk_count
            continue

        document_id = hashlib.sha256(
            f"{organization_id}:{content_hash}".encode("utf-8")
        ).hexdigest()
        latest_version = session.scalar(
            select(func.max(DocumentRecord.version)).where(
                DocumentRecord.organization_id == organization_id,
                DocumentRecord.source == source,
            )
        )
        version = (latest_version or 0) + 1
        chunks = chunk_document_text(text)
        if not chunks:
            raise ValueError(f"Synthetic evidence source is empty: {source}")
        session.add(
            DocumentRecord(
                id=document_id,
                organization_id=organization_id,
                source=source,
                content_hash=content_hash,
                version=version,
                metadata_json={
                    "extension": source.rsplit(".", 1)[-1],
                    "source_type": "synthetic_simulator",
                    "scenario_id": scenario_id,
                    "synthetic": True,
                    "version": version,
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
                        "source": source,
                        "source_type": "synthetic_simulator",
                        "scenario_id": scenario_id,
                        "synthetic": True,
                        "version": version,
                    },
                )
            )
        documents.append(
            {
                "document_id": document_id,
                "source": source,
                "chunk_count": len(chunks),
            }
        )
        total_chunks += len(chunks)

    return {
        "scenario_id": scenario_id,
        "synthetic": True,
        "documents": documents,
        "document_count": len(documents),
        "chunk_count": total_chunks,
    }

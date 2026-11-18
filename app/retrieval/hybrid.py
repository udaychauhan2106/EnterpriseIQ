import hashlib
import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, settings
from app.domain.models import RetrievedEvidence
from app.persistence.database import DocumentChunkRecord

logger = logging.getLogger(__name__)
_TOKEN = re.compile(r"[a-z0-9][a-z0-9_.:/-]*", re.IGNORECASE)


@dataclass(frozen=True)
class CorpusChunk:
    source_id: str
    document_id: str
    chunk_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    evidence: list[RetrievedEvidence]
    mode: str
    warnings: list[str] = field(default_factory=list)


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN.findall(text)]


def _local_chunks(
    session: Session,
    organization_id: str,
    simulation_scenario_id: str | None = None,
) -> list[CorpusChunk]:
    chunks: list[CorpusChunk] = []
    rows = session.scalars(
        select(DocumentChunkRecord).where(
            DocumentChunkRecord.organization_id == organization_id
        )
    ).all()
    for row in rows:
        metadata = row.metadata_json or {}
        if (
            simulation_scenario_id
            and metadata.get("scenario_id") != simulation_scenario_id
        ):
            continue
        chunks.append(
            CorpusChunk(
                source_id=str(metadata.get("source_type", "uploaded")),
                document_id=row.document_id,
                chunk_id=row.id,
                text=row.text,
                metadata={
                    "source": metadata.get("source", "Uploaded document"),
                    "source_type": metadata.get("source_type", "uploaded"),
                    "scenario_id": metadata.get("scenario_id"),
                    "synthetic": metadata.get("synthetic", False),
                },
            )
        )

    processed_dir = Path(settings.ENTERPRISEIQ_PROCESSED_DATA_DIR or PROJECT_ROOT / "processed_data")
    if not processed_dir.is_absolute():
        processed_dir = PROJECT_ROOT / processed_dir
    if not simulation_scenario_id and processed_dir.exists():
        for path in sorted(processed_dir.glob("*/*.json")):
            if path.name == "failed_files.json":
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                source = str(data.get("filename") or path.stem.removesuffix(".pdf"))
                source_type = str(data.get("source_type") or path.parent.name)
                document_id = hashlib.sha256(
                    f"{source_type}:{source}".encode("utf-8")
                ).hexdigest()
                for index, text in enumerate(data.get("chunks", [])):
                    if not isinstance(text, str) or not text.strip():
                        continue
                    chunk_id = hashlib.sha256(
                        f"{document_id}:{index}".encode("utf-8")
                    ).hexdigest()
                    chunks.append(
                        CorpusChunk(
                            source_id=source_type,
                            document_id=document_id,
                            chunk_id=chunk_id,
                            text=text,
                            metadata={
                                "source": source,
                                "source_type": source_type,
                                "chunk_index": index,
                            },
                        )
                    )
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                logger.warning("Skipping unreadable processed document %s: %s", path, exc)
    return chunks


def _bm25_scores(query: str, chunks: list[CorpusChunk]) -> list[tuple[int, float]]:
    query_tokens = _tokenize(query)
    if not query_tokens or not chunks:
        return []

    tokenized = [_tokenize(chunk.text) for chunk in chunks]
    document_frequency: Counter[str] = Counter()
    for tokens in tokenized:
        document_frequency.update(set(tokens))

    average_length = sum(map(len, tokenized)) / max(1, len(tokenized))
    k1 = 1.5
    b = 0.75
    scored: list[tuple[int, float]] = []
    for index, tokens in enumerate(tokenized):
        counts = Counter(tokens)
        score = 0.0
        for term in query_tokens:
            frequency = counts[term]
            if not frequency:
                continue
            idf = math.log(
                1 + (len(chunks) - document_frequency[term] + 0.5)
                / (document_frequency[term] + 0.5)
            )
            denominator = frequency + k1 * (
                1 - b + b * len(tokens) / max(1, average_length)
            )
            score += idf * frequency * (k1 + 1) / denominator
        if score > 0:
            scored.append((index, score))
    return sorted(scored, key=lambda item: item[1], reverse=True)


def _dense_rankings(
    query: str, organization_id: str
) -> tuple[list[tuple[str, float]], str | None]:
    if not settings.QUADRANT_URL:
        return [], None
    try:
        from qdrant_client import QdrantClient, models

        from app.services.retrieval.embeddings import embed_query

        client = QdrantClient(
            url=settings.QUADRANT_URL,
            api_key=settings.QUADRANT_API_KEY,
            timeout=10,
        )
        result = client.query_points(
            collection_name=settings.QUADRANT_COLLECTION,
            query=embed_query(query),
            limit=settings.ENTERPRISEIQ_MAX_RETRIEVAL_RESULTS,
            with_payload=True,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="organization_id",
                        match=models.MatchValue(value=organization_id),
                    )
                ]
            ),
        )
        rows = []
        for point in result.points:
            payload = point.payload or {}
            source = str(payload.get("source", "unknown"))
            chunk_index = str(payload.get("chunk_index", "0"))
            identity = hashlib.sha256(
                f"{payload.get('source_type', 'general')}:{source}".encode("utf-8")
            ).hexdigest()
            chunk_id = hashlib.sha256(
                f"{identity}:{chunk_index}".encode("utf-8")
            ).hexdigest()
            rows.append((chunk_id, float(point.score or 0)))
        return rows, None
    except Exception as exc:
        logger.warning("Dense retrieval is unavailable: %s", exc)
        return [], f"Dense Qdrant retrieval unavailable ({type(exc).__name__}); lexical results only."


def hybrid_search(
    query: str,
    session: Session,
    organization_id: str = "local",
    *,
    limit: int = 8,
    source_type: str | None = None,
    simulation_scenario_id: str | None = None,
) -> RetrievalResult:
    """Search local and indexed knowledge with BM25 and optional Qdrant fusion."""
    chunks = _local_chunks(session, organization_id, simulation_scenario_id)
    if source_type:
        chunks = [
            chunk
            for chunk in chunks
            if chunk.metadata.get("source_type", chunk.source_id) == source_type
        ]
    sparse = _bm25_scores(query, chunks)
    dense, dense_warning = (
        _dense_rankings(query, organization_id)
        if settings.ENTERPRISEIQ_ENABLE_EXTERNAL_RETRIEVAL
        else ([], None)
    )
    dense_positions = {chunk_id: (rank, score) for rank, (chunk_id, score) in enumerate(dense, 1)}

    fused: list[tuple[int, float]] = []
    sparse_positions = {index: (rank, score) for rank, (index, score) in enumerate(sparse, 1)}
    for index, sparse_score in sparse:
        chunk_id = chunks[index].chunk_id
        dense_rank = dense_positions.get(chunk_id)
        reciprocal_rank_score = 1.0 / (60 + sparse_positions[index][0])
        if dense_rank:
            reciprocal_rank_score += 1.0 / (60 + dense_rank[0])
        fused.append((index, reciprocal_rank_score))
    fused.sort(key=lambda item: item[1], reverse=True)

    evidence: list[RetrievedEvidence] = []
    now = datetime.now(timezone.utc)
    for index, rank_score in fused[: min(limit, settings.ENTERPRISEIQ_MAX_RETRIEVAL_RESULTS)]:
        chunk = chunks[index]
        dense_match = dense_positions.get(chunk.chunk_id)
        sparse_score = sparse_positions[index][1]
        evidence.append(
            RetrievedEvidence(
                evidence_id=f"ev-{chunk.chunk_id[:16]}",
                source_id=chunk.source_id,
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                excerpt=chunk.text[:2000],
                metadata=chunk.metadata,
                sparse_score=sparse_score,
                dense_score=dense_match[1] if dense_match else None,
                retrieval_score=rank_score,
                retrieved_at=now,
            )
        )
    warnings = [dense_warning] if dense_warning else []
    if not settings.ENTERPRISEIQ_ENABLE_EXTERNAL_RETRIEVAL:
        warnings.append(
            "External dense retrieval is disabled; results use BM25 lexical ranking only."
        )
    elif not dense and not dense_warning:
        warnings.append("Qdrant returned no dense matches; results use BM25 lexical ranking only.")
    mode = "hybrid" if dense else "bm25"
    return RetrievalResult(evidence=evidence, mode=mode, warnings=warnings)

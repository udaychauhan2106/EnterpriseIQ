import os
import json
import logging
import time
import uuid

from qdrant_client import QdrantClient
from qdrant_client.http import models

from app import settings
from app.services.retrieval.embeddings import (
    embed_texts,
    get_embedding_dim,
    QuotaExhausted,
)
from app.ingestion.loaders.pdf import parse_pdf
from app.ingestion.loaders.html import parse_html
from app.ingestion.loaders.office import parse_office
from app.ingestion.loaders.text import parse_text
from app.ingestion.chunking.splitter import chunk_text

logger = logging.getLogger(__name__)

PROCESSED_DATA_DIR = "processed_data"
FAILED_FILES_PATH = os.path.join(PROCESSED_DATA_DIR, "failed_files.json")
 
PARSERS = {
    "pdf": parse_pdf,
    "html": parse_html,
    "htm": parse_html,
    "txt": parse_text,
    "docx": parse_office,
    "pptx": parse_office,
}
QDRANT_BATCH_SIZE = 50
QDRANT_MAX_RETRIES = 4
 
qdrant_client = QdrantClient(
    url=settings.QUADRANT_URL,
    api_key=settings.QUADRANT_API_KEY,
)
 
 
def ensure_collection(wipe: bool = False) -> None:
    collection_name = settings.QUADRANT_COLLECTION
    exists = qdrant_client.collection_exists(collection_name)
 
    if wipe and exists:
        logger.warning("Deleting existing Qdrant collection %s", collection_name)
        qdrant_client.delete_collection(collection_name=collection_name)
        exists = False
 
    dim = get_embedding_dim()
 
    if not exists:
        qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=dim,
                distance=models.Distance.COSINE,
            ),
        )
        logger.info("Created Qdrant collection %s with %d dimensions", collection_name, dim)
    else:

        info = qdrant_client.get_collection(collection_name)
        existing_dim = info.config.params.vectors.size
        if existing_dim != dim:
            raise RuntimeError(
                f"Active embedding model produces {dim}-dim vectors but the "
                f"existing Qdrant collection '{collection_name}' expects "
                f"{existing_dim}-dim vectors. Either fix model availability "
                f"(e.g. restore Gemini access) or run with --wipe to rebuild "
                f"the collection at the new dimension."
            )
 
 
def upsert_points_batched(points: list[models.PointStruct]) -> None:
    total_points = len(points)
 
    for start in range(0, total_points, QDRANT_BATCH_SIZE):
        batch = points[start:start + QDRANT_BATCH_SIZE]
 
        for attempt in range(QDRANT_MAX_RETRIES):
            try:
                qdrant_client.upsert(
                    collection_name=settings.QUADRANT_COLLECTION,
                    points=batch,
                    wait=True,
                )
                logger.info("Indexed Qdrant batch starting at %d with %d points", start, len(batch))
                break
            except Exception as e:
                if attempt == QDRANT_MAX_RETRIES - 1:
                    raise
                wait_seconds = 2 ** attempt
                logger.warning(
                    "Qdrant upsert failed; retrying attempt %d in %d seconds: %s",
                    attempt + 1,
                    wait_seconds,
                    e,
                )
                time.sleep(wait_seconds)
 
 
def create_point_id(
    filename: str,
    source_type: str,
    chunk_index: int,
) -> str:

    raw_id = f"{source_type}:{filename}:{chunk_index}"

    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            raw_id,
        )
    )
 
 
def save_processed_locally(data: dict, source_type: str, filename: str) -> str:
    """Save parsed chunk metadata as JSON in processed_data/<source_type>/."""
    folder = os.path.join(PROCESSED_DATA_DIR, source_type)
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, f"{filename}.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return dest
 
 
def load_failed_files() -> list[dict]:
    if not os.path.exists(FAILED_FILES_PATH):
        return []
    with open(FAILED_FILES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)
 
 
def save_failed_files(failed: list[dict]) -> None:
    os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)
    with open(FAILED_FILES_PATH, "w", encoding="utf-8") as f:
        json.dump(failed, f, ensure_ascii=False, indent=2)
    if failed:
        logger.warning("%d file(s) failed to index. See %s", len(failed), FAILED_FILES_PATH)
 
 
def process_file(file_path: str, filename: str, source_type: str) -> None:
    """Parse -> chunk -> save locally -> embed -> index in Qdrant.
 
    Raises QuotaExhausted if Gemini's daily quota is hit, so callers can
    halt the run instead of silently skipping every remaining file.
    """
    ext = filename.lower().rsplit(".", 1)[-1]
    parser = PARSERS.get(ext)

    if parser is None:
        logger.warning("Skipping unsupported file type: %s", filename)
        return

    full_text = parser(file_path)

    if not full_text or not full_text.strip():
        logger.warning("No text extracted from %s; skipping", filename)
        return

    chunks = chunk_text(full_text)
    if not chunks:
        return

    processed_data = {
        "filename": filename,
        "source_type": source_type,
        "chunks": chunks,
    }
    local_path = save_processed_locally(processed_data, source_type, filename)
    logger.info("Saved processed data to %s", local_path)

    embeddings = embed_texts(chunks)

    if len(chunks) != len(embeddings):
        raise ValueError(
            f"Chunk/embedding count mismatch: "
            f"{len(chunks)} chunks vs {len(embeddings)} embeddings"
        )

    expected_dim = get_embedding_dim()
    for index, vector in enumerate(embeddings):
        if len(vector) != expected_dim:
            raise ValueError(
                f"Invalid embedding dimension for chunk {index}: "
                f"expected {expected_dim}, got {len(vector)}"
            )

    points = [
        models.PointStruct(
            id=create_point_id(filename, source_type, chunk_index),
            vector=vector,
            payload={
                "text": chunk,
                "source": filename,
                "source_type": source_type,
                "chunk_index": chunk_index,
                "organization_id": "local",
            },
        )
        for chunk_index, (chunk, vector) in enumerate(zip(chunks, embeddings))
    ]
    upsert_points_batched(points)
    logger.info("Indexed %d points to Qdrant from %s", len(points), filename)
 
 
def _iter_files_recursive(dir_path: str):
    """Yield (full_path, filename) for every file under dir_path, including subfolders."""
    for root, _dirs, files in os.walk(dir_path):
        for filename in files:
            yield os.path.join(root, filename), filename
 
 
def process_directory(dir_path: str, source_type: str, failed_files: list[dict]) -> bool:
    """Process every file in a directory (recursively).
 
    Returns False and stops early if Gemini's daily quota is exhausted mid-run;
    True if the directory was fully processed (individual file errors are
    recorded in failed_files, not raised).
    """
    entries = list(_iter_files_recursive(dir_path))
    logger.info("Found %d files under %s", len(entries), dir_path)

    for full_path, filename in entries:
        try:
            process_file(full_path, filename, source_type)
        except QuotaExhausted:
            logger.error(
                "Gemini daily quota exhausted while processing %s. Halting ingestion.",
                filename,
            )
            failed_files.append({
                "path": full_path,
                "filename": filename,
                "source_type": source_type,
                "reason": "quota_exhausted",
            })
            return False
        except Exception:
            logger.exception("Failed to process %s as source type %s", filename, source_type)
            failed_files.append({
                "path": full_path,
                "filename": filename,
                "source_type": source_type,
                "reason": "error",
            })
    return True
 
 
def run_universal_ingestion(base_dir: str, explicit_source_type: str = None, wipe: bool = False):
    """Scan base_dir, map sub-folders to source types, and ingest all documents.
    Pass --wipe to drop and recreate the Qdrant collection before ingestion.
 
    On Gemini quota exhaustion, stops early (rather than silently skipping
    files) and writes remaining/failed files to processed_data/failed_files.json
    so the run can be resumed later without rescanning everything.
    """
    failed_files: list[dict] = []

    ensure_collection(wipe=wipe)

    subdirs = [
        d for d in os.listdir(base_dir)
        if os.path.isdir(os.path.join(base_dir, d))
    ]

    if not subdirs:
        if explicit_source_type:
            source_type = explicit_source_type
        else:
            base_name = os.path.basename(os.path.normpath(base_dir)).lower()
            source_type = (
                "true" if "true" in base_name
                else "noise" if "noise" in base_name
                else "general"
            )
        logger.info("No sub-folder found; processing %s as %s", base_dir, source_type)
        process_directory(base_dir, source_type, failed_files)
    else:
        for subdir in subdirs:
            source_type = (
                "true" if "true" in subdir.lower()
                else "noisy" if "noisy" in subdir.lower()
                else subdir
            )
            completed = process_directory(
                os.path.join(base_dir, subdir), source_type, failed_files
            )
            if not completed:
                break

    save_failed_files(failed_files)
    return failed_files
 
 
def retry_failed_files():
    """Re-attempt only the files recorded in failed_files.json.
    Successfully processed files are removed from the list; anything that
    fails again (including a fresh quota exhaustion) is written back."""
    failed = load_failed_files()
    if not failed:
        logger.info("No failed files to retry")
        return

    still_failed: list[dict] = []
    for entry in failed:
        try:
            process_file(entry["path"], entry["filename"], entry["source_type"])
        except QuotaExhausted:
            logger.error("Gemini quota exhausted again; stopping retry pass")
            still_failed.append({**entry, "reason": "quota_exhausted"})
            still_failed.extend(failed[len(still_failed):])  # keep the rest un-retried
            break
        except Exception:
            logger.exception("Retry failed again for %s", entry["filename"])
            still_failed.append({**entry, "reason": "error"})
 
    save_failed_files(still_failed)

 
if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
 
    parser.add_argument(
        "base_dir",
        nargs="?",
        default=None,
        help="Directory containing documents to ingest",
    )
 
    parser.add_argument(
        "--source-type",
        default=None,
        help="Explicit source type when ingesting a single directory",
    )
 
    parser.add_argument(
        "--wipe",
        action="store_true",
        help="Delete and recreate the Qdrant collection before ingestion",
    )
 
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry only files listed in processed_data/failed_files.json",
    )
 
    args = parser.parse_args()
 
    if args.retry_failed:
        retry_failed_files()
    else:
        if not args.base_dir:
            parser.error("base_dir is required unless --retry-failed is set")
        run_universal_ingestion(
            base_dir=args.base_dir,
            explicit_source_type=args.source_type,
            wipe=args.wipe,
        )
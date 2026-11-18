import logging

from qdrant_client import QdrantClient

from app.config import settings
from app.services.retrieval.embeddings import embed_query

logger = logging.getLogger(__name__)

client = QdrantClient(
    url=settings.QUADRANT_URL,
    api_key=settings.QUADRANT_API_KEY
)

def search_enterprise_knowledge(query: str, limit: int = 8):
    """
    Performs a high-precision search in the enterprise knowledge base.
    Uses the modern query_points interface.
    """
    try:
        query_vector = embed_query(query)

        response = client.query_points(
            collection_name=settings.QUADRANT_COLLECTION,
            query=query_vector,
            limit=limit,
            with_payload=True 
        )

        results = []
        for res in response.points:
            results.append({
                "content": res.payload.get("text", ""),
                "source": res.payload.get("source", "Unknown"),
                "score": res.score
            })
        
        return results
    except Exception as exc:
        logger.exception("Qdrant search failed")
        raise RuntimeError("Enterprise knowledge search failed.") from exc
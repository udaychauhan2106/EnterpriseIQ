import math
import re
from collections.abc import Sequence

_CITATION = re.compile(r"\[([A-Za-z0-9_-]+)\]")


def retrieval_metrics(
    expected_ids: Sequence[str], retrieved_ids: Sequence[str], k: int
) -> dict[str, float]:
    """Compute binary relevance Recall@K, Precision@K, MRR, and nDCG."""
    expected = set(expected_ids)
    ranked = list(retrieved_ids[:k])
    if not expected:
        return {
            "recall_at_k": 1.0 if not ranked else 0.0,
            "precision_at_k": 0.0,
            "mrr": 0.0,
            "ndcg": 0.0,
        }
    relevant = [1 if item in expected else 0 for item in ranked]
    hits = sum(relevant)
    reciprocal_rank = next(
        (1.0 / position for position, is_relevant in enumerate(relevant, 1) if is_relevant),
        0.0,
    )
    dcg = sum(
        is_relevant / math.log2(position + 1)
        for position, is_relevant in enumerate(relevant, 1)
    )
    ideal_count = min(len(expected), k)
    idcg = sum(1 / math.log2(position + 1) for position in range(1, ideal_count + 1))
    return {
        "recall_at_k": hits / len(expected),
        "precision_at_k": hits / max(1, k),
        "mrr": reciprocal_rank,
        "ndcg": dcg / idcg if idcg else 0.0,
    }


def generation_metrics(
    answer: str,
    known_facts: Sequence[str],
    valid_evidence_ids: set[str],
) -> dict[str, float]:
    """Measure exact labelled-fact support and citation validity for an answer."""
    normalized_answer = " ".join(answer.casefold().split())
    supported_facts = sum(
        " ".join(fact.casefold().split()) in normalized_answer
        for fact in known_facts
    )
    citations = _CITATION.findall(answer)
    valid_citations = sum(citation in valid_evidence_ids for citation in citations)
    sentence_like_claims = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", answer)
        if sentence.strip()
    ]
    cited_claims = sum(bool(_CITATION.search(claim)) for claim in sentence_like_claims)
    return {
        "answer_relevance": supported_facts / max(1, len(known_facts)),
        "faithfulness": supported_facts / max(1, len(sentence_like_claims)),
        "citation_correctness": valid_citations / max(1, len(citations)),
        "citation_coverage": cited_claims / max(1, len(sentence_like_claims)),
        "unsupported_claim_rate": (len(sentence_like_claims) - cited_claims)
        / max(1, len(sentence_like_claims)),
    }


def agent_metrics(
    *,
    completed: bool,
    expected_tools: Sequence[str],
    selected_tools: Sequence[str],
    successful_tools: int,
    retry_count: int,
) -> dict[str, float]:
    expected = set(expected_tools)
    selected = set(selected_tools)
    correct = len(expected & selected)
    return {
        "task_completion_rate": float(completed),
        "tool_selection_accuracy": correct / max(1, len(expected)),
        "tool_execution_success_rate": successful_tools / max(1, len(selected_tools)),
        "retry_frequency": float(retry_count),
    }


def system_metrics(
    *, latency_seconds: float, token_count: int, cost_usd: float, failed: bool
) -> dict[str, float]:
    return {
        "end_to_end_latency_seconds": latency_seconds,
        "token_usage": float(token_count),
        "cost_per_investigation_usd": cost_usd,
        "error_rate": float(failed),
    }

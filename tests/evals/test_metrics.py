from evals.metrics import agent_metrics, generation_metrics, retrieval_metrics, system_metrics


def test_retrieval_metrics_compute_ranked_relevance() -> None:
    result = retrieval_metrics(["b", "c"], ["x", "b", "c"], k=3)

    assert result == {
        "recall_at_k": 1.0,
        "precision_at_k": 2 / 3,
        "mrr": 0.5,
        "ndcg": (1 / 2 + 1 / 1.584962500721156) / (1 + 1 / 1.584962500721156),
    }


def test_generation_metrics_flag_missing_or_invalid_citations() -> None:
    result = generation_metrics(
        "The runbook recommends comparing request IDs [ev-1]. The release caused the outage.",
        ["The runbook recommends comparing request IDs"],
        {"ev-1"},
    )

    assert result["citation_correctness"] == 1.0
    assert result["citation_coverage"] == 0.5
    assert result["unsupported_claim_rate"] == 0.5


def test_agent_and_system_metrics_use_observed_execution_inputs() -> None:
    agent = agent_metrics(
        completed=True,
        expected_tools=["logs", "deployments"],
        selected_tools=["logs"],
        successful_tools=1,
        retry_count=0,
    )
    system = system_metrics(
        latency_seconds=2.5,
        token_count=0,
        cost_usd=0.0,
        failed=False,
    )

    assert agent["task_completion_rate"] == 1.0
    assert agent["tool_selection_accuracy"] == 0.5
    assert system["end_to_end_latency_seconds"] == 2.5
    assert system["error_rate"] == 0.0

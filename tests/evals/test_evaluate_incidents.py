import json

import pytest

from app.simulator.ground_truth import write_ground_truth_files
from evals.evaluate_incidents import evaluate_incident, evaluate_results


def test_evaluator_scores_structured_result_against_synthetic_truth(tmp_path) -> None:
    truth_dir = tmp_path / "truth"
    write_ground_truth_files(truth_dir, ("INC-001",))
    result = {
        "scenario_id": "INC-001",
        "first_symptom_offset_seconds": 120,
        "affected_services": ["api-gateway", "payment-service", "postgresql"],
        "timeline": [
            {"offset_seconds": 0, "event": "Payment worker concurrency deployment"},
            {"offset_seconds": 120, "event": "Payment connection acquisition timeout"},
            {"offset_seconds": 180, "event": "Database connections near the configured maximum"},
            {"offset_seconds": 240, "event": "API errors and latency rise"},
            {"offset_seconds": 600, "event": "Concurrency rollback"},
        ],
        "report": {
            "summary": (
                "Payment worker concurrency exhausted the database connection pool "
                "after connection acquisition failures."
            ),
            "findings": [
                {"statement": "Connection acquisition timed out.", "evidence_refs": [{"evidence_id": "ev-1"}]}
            ],
            "evidence": [
                {
                    "evidence_id": "ev-1",
                    "metadata": {"source": "Nexora/INC-001/logs/application.log"},
                    "excerpt": "Payment connection acquisition timed out.",
                },
                {
                    "evidence_id": "ev-2",
                    "metadata": {"source": "Nexora/INC-001/logs/infrastructure.log"},
                    "excerpt": "Database active connections reached 96 of 100.",
                },
                {
                    "evidence_id": "ev-3",
                    "metadata": {"source": "Nexora/INC-001/deployment_history.json"},
                    "excerpt": "Worker concurrency changed from 20 to 60.",
                },
                {
                    "evidence_id": "ev-4",
                    "metadata": {"source": "Nexora/INC-001/metrics.csv"},
                    "excerpt": "db.connection_utilization increased.",
                },
            ],
            "recommended_actions": [
                "Restore safe worker concurrency.",
                "Tune pool and concurrency together.",
                "Alert on acquisition waiters and connection saturation.",
            ],
        },
    }
    score = evaluate_results([result], truth_dir)["incidents"][0]

    assert score["root_cause_keyword_coverage"] == 1
    assert score["evidence_retrieval_recall"] == 1
    assert score["valid_citation_rate"] == 1
    assert score["timeline_reconstruction_recall"] == 1
    assert score["first_symptom_offset_error_seconds"] == 0
    assert score["unsupported_claim_rate"] == 0
    assert score["affected_service_recall"] == 1


def test_evaluator_does_not_score_empty_results_or_missing_truth(tmp_path) -> None:
    with pytest.raises(ValueError, match="No investigation results"):
        evaluate_results([], tmp_path)
    with pytest.raises(FileNotFoundError):
        evaluate_results([{"scenario_id": "INC-001"}], tmp_path)


def test_evaluator_reports_missing_claim_citations_as_unsupported(tmp_path) -> None:
    truth_dir = tmp_path / "truth"
    write_ground_truth_files(truth_dir, ("INC-001",))
    score = evaluate_incident(
        {
            "scenario_id": "INC-001",
            "report": {
                "summary": "Unknown.",
                "findings": [{"statement": "Uncited assertion", "evidence_refs": []}],
                "evidence": [],
            },
        },
        json.loads(
            (truth_dir / "INC-001" / "ground_truth.json").read_text(encoding="utf-8")
        ),
    )
    assert score["unsupported_claim_rate"] == 1
    assert score["evidence_retrieval_recall"] == 0

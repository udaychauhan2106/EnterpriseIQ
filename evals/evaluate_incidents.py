"""Score structured EnterpriseIQ investigation exports against synthetic truth."""

import argparse
import json
import re
from pathlib import Path
from statistics import mean
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GROUND_TRUTH_DIR = (
    PROJECT_ROOT / "simulator_data" / "nexora" / "ground_truth"
)
_WORDS = re.compile(r"[a-z0-9][a-z0-9-]*", re.IGNORECASE)


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_text(item) for item in value.values())
    return ""


def _tokens(value: Any) -> set[str]:
    return {
        token.casefold()
        for token in _WORDS.findall(_text(value))
        if len(token) > 2
    }


def _coverage(expected: list[str], actual: Any) -> float | None:
    if not expected:
        return None
    actual_text = _text(actual).casefold()
    return sum(item.casefold() in actual_text for item in expected) / len(expected)


def _source(evidence: dict[str, Any]) -> str:
    metadata = evidence.get("metadata")
    if isinstance(metadata, dict):
        return str(metadata.get("source") or evidence.get("source_id") or "")
    return str(evidence.get("source_id") or "")


def _resolve_evidence(
    result: dict[str, Any], report: dict[str, Any]
) -> list[dict[str, Any]]:
    evidence = report.get("evidence", result.get("evidence", []))
    return [item for item in evidence if isinstance(item, dict)] if isinstance(evidence, list) else []


def _referenced_ids(value: Any) -> set[str]:
    references: set[str] = set()
    if isinstance(value, dict):
        evidence_id = value.get("evidence_id")
        if isinstance(evidence_id, str):
            references.add(evidence_id)
        for nested in value.values():
            references.update(_referenced_ids(nested))
    elif isinstance(value, list):
        for nested in value:
            references.update(_referenced_ids(nested))
    return references


def _timeline_match(expected: dict[str, Any], actual_events: list[Any]) -> bool:
    expected_words = _tokens(expected.get("event", ""))
    if not expected_words:
        return False
    target_offset = expected.get("offset_seconds")
    for event in actual_events:
        actual_words = _tokens(event)
        overlap = len(expected_words & actual_words) / len(expected_words)
        if overlap < 0.5:
            continue
        if isinstance(event, dict) and isinstance(target_offset, (int, float)):
            actual_offset = event.get("offset_seconds")
            if isinstance(actual_offset, (int, float)) and abs(actual_offset - target_offset) > 60:
                continue
        return True
    return False


def _phrase_match_rate(expected: list[str], actual: Any) -> float | None:
    if not expected:
        return None
    actual_items = actual if isinstance(actual, list) else [actual]
    actual_token_sets = [_tokens(item) for item in actual_items]
    matched = 0
    for phrase in expected:
        phrase_tokens = _tokens(phrase)
        if any(
            phrase_tokens
            and len(phrase_tokens & actual_tokens) / len(phrase_tokens) >= 0.5
            for actual_tokens in actual_token_sets
        ):
            matched += 1
    return matched / len(expected)


def evaluate_incident(
    result: dict[str, Any], ground_truth: dict[str, Any]
) -> dict[str, Any]:
    report_value = result.get("report", result)
    report = report_value if isinstance(report_value, dict) else {}
    evidence = _resolve_evidence(result, report)
    evidence_by_id = {
        str(item["evidence_id"]): item
        for item in evidence
        if isinstance(item.get("evidence_id"), str)
    }
    relevant = ground_truth["relevant_evidence_identifiers"]
    retrieved_relevant = [
        identifier
        for identifier in relevant
        if any(
            identifier["artifact"].casefold() in _source(item).casefold()
            and identifier["contains"].casefold()
            in str(item.get("excerpt", "")).casefold()
            for item in evidence
        )
    ]
    cited_ids = _referenced_ids(
        {
            "findings": report.get("findings", []),
            "hypotheses": report.get("hypotheses", []),
            "conflicts": report.get("conflicts", []),
            "claims": result.get("claims", []),
        }
    )
    valid_citations = cited_ids & evidence_by_id.keys()
    relevant_artifacts = [
        identifier["artifact"].casefold() for identifier in relevant
    ]
    relevant_citations = {
        citation_id
        for citation_id in valid_citations
        if any(
            artifact in _source(evidence_by_id[citation_id]).casefold()
            for artifact in relevant_artifacts
        )
    }
    claims = result.get("claims", report.get("findings", []))
    claims = claims if isinstance(claims, list) else []
    unsupported_claims = [
        claim
        for claim in claims
        if not (_referenced_ids(claim) & evidence_by_id.keys())
    ]
    expected_timeline = ground_truth["expected_timeline"]
    actual_timeline = result.get("timeline", [])
    actual_timeline = actual_timeline if isinstance(actual_timeline, list) else []
    matched_timeline = [
        expected
        for expected in expected_timeline
        if _timeline_match(expected, actual_timeline)
    ]

    report_text = " ".join(
        (
            _text(report.get("summary", "")),
            _text(report.get("findings", [])),
            _text(report.get("hypotheses", [])),
        )
    ).casefold()
    keywords = ground_truth["root_cause_keywords"]
    action_text = report.get("recommended_actions", result.get("recommended_actions", []))
    action_tokens = _tokens(action_text)
    expected_action_tokens = set().union(
        *(_tokens(action) for action in ground_truth["corrective_actions"])
    )
    affected_expected = set(result.get("affected_services", []))
    affected_expected_services = set(ground_truth["affected_services"])
    first_symptom_expected = next(
        (
            item["offset_seconds"]
            for item in expected_timeline
            if item["offset_seconds"] > 0
        ),
        0,
    )
    first_symptom_actual = result.get("first_symptom_offset_seconds")
    expected_deployment = expected_timeline[0].get("event", "") if expected_timeline else ""
    actual_deployment = result.get("deployment", result.get("deployment_id", ""))
    hypotheses = report.get("hypotheses", result.get("hypotheses", []))
    contradictory_evidence = result.get(
        "contradictory_evidence", report.get("conflicts", [])
    )
    timeline_recall = (
        len(matched_timeline) / len(expected_timeline) if expected_timeline else None
    )
    return {
        "scenario_id": ground_truth["scenario_id"],
        "root_cause_keyword_coverage": _coverage(keywords, report_text),
        "evidence_retrieval_recall": (
            len(retrieved_relevant) / len(relevant) if relevant else None
        ),
        "retrieved_evidence_identifiers": [
            item["artifact"] for item in retrieved_relevant
        ],
        "valid_citation_rate": (
            len(valid_citations) / len(cited_ids) if cited_ids else None
        ),
        "relevant_citation_rate": (
            len(relevant_citations) / len(cited_ids) if cited_ids else None
        ),
        "timeline_reconstruction_recall": timeline_recall,
        "timeline_events_matched": len(matched_timeline),
        "timeline_events_expected": len(expected_timeline),
        "deployment_recognition": _phrase_match_rate(
            [expected_deployment] if expected_deployment else [],
            actual_deployment,
        ),
        "first_symptom_offset_error_seconds": (
            abs(first_symptom_actual - first_symptom_expected)
            if isinstance(first_symptom_actual, (int, float))
            else None
        ),
        "unsupported_claim_rate": (
            len(unsupported_claims) / len(claims) if claims else None
        ),
        "recommended_action_keyword_coverage": (
            len(action_tokens & expected_action_tokens) / len(expected_action_tokens)
            if expected_action_tokens
            else None
        ),
        "affected_service_recall": (
            len(affected_expected & affected_expected_services)
            / len(affected_expected_services)
            if affected_expected_services
            else None
        ),
        "acceptable_hypothesis_coverage": _phrase_match_rate(
            ground_truth["acceptable_hypotheses"], hypotheses
        ),
        "contradictory_evidence_coverage": _phrase_match_rate(
            ground_truth["misleading_evidence"], contradictory_evidence
        ),
    }


def evaluate_results(
    results: list[dict[str, Any]], ground_truth_dir: Path
) -> dict[str, Any]:
    if not results:
        raise ValueError("No investigation results were provided.")
    scores: list[dict[str, Any]] = []
    for result in results:
        scenario_id = result.get("scenario_id")
        if not isinstance(scenario_id, str) or not re.fullmatch(r"INC-\d{3}", scenario_id):
            raise ValueError("Each result must include a valid scenario_id.")
        truth_path = ground_truth_dir / scenario_id / "ground_truth.json"
        ground_truth = json.loads(truth_path.read_text(encoding="utf-8"))
        if ground_truth.get("synthetic") is not True:
            raise ValueError(f"Ground truth is missing its synthetic marker: {truth_path}")
        if ground_truth.get("scenario_id") != scenario_id:
            raise ValueError(f"Ground-truth scenario mismatch: {truth_path}")
        scores.append(evaluate_incident(result, ground_truth))

    metric_names = (
        "root_cause_keyword_coverage",
        "evidence_retrieval_recall",
        "valid_citation_rate",
        "relevant_citation_rate",
        "timeline_reconstruction_recall",
        "deployment_recognition",
        "first_symptom_offset_error_seconds",
        "unsupported_claim_rate",
        "recommended_action_keyword_coverage",
        "affected_service_recall",
        "acceptable_hypothesis_coverage",
        "contradictory_evidence_coverage",
    )
    averages = {
        metric: mean(
            value
            for score in scores
            if (value := score[metric]) is not None
        )
        if any(score[metric] is not None for score in scores)
        else None
        for metric in metric_names
    }
    return {
        "synthetic_evaluation": True,
        "results_count": len(scores),
        "averages": averages,
        "incidents": scores,
        "limitations": [
            "Root-cause and action scores are lexical coverage heuristics, not expert judgments.",
            "Citation scoring checks identifier validity and source relevance, not semantic entailment.",
            "Timeline scoring uses token overlap and a 60-second offset tolerance.",
            "Missing result fields are reported as null and are not treated as successful.",
        ],
    }


def _load_results(path: Path) -> list[dict[str, Any]]:
    content = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        payload = [json.loads(line) for line in content.splitlines() if line.strip()]
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError("Results must be a JSON object, array, or JSONL objects.")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate structured synthetic Nexora incident investigation results."
    )
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument(
        "--ground-truth-dir", type=Path, default=DEFAULT_GROUND_TRUTH_DIR
    )
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    evaluation = evaluate_results(
        _load_results(arguments.results), arguments.ground_truth_dir
    )
    rendered = json.dumps(evaluation, indent=2, sort_keys=True) + "\n"
    if arguments.output:
        arguments.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()

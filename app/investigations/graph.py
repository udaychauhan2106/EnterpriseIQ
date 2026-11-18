import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, StateGraph
from app.domain.models import (
    EvidenceConflict,
    EvidenceReference,
    Finding,
    FindingClassification,
    InvestigationPlan,
    InvestigationTask,
    RetrievedEvidence,
    UnresolvedQuestion,
)
from app.persistence.database import get_session_factory
from app.retrieval.hybrid import hybrid_search
from app.tools.mock_tools import run_read_only_tools


_WORD = re.compile(r"[a-z0-9][a-z0-9_.:/-]*", re.IGNORECASE)
_CONFLICT_PAIRS = (
    ("completed", "failed"),
    ("successful", "failed"),
    ("healthy", "unhealthy"),
    ("available", "unavailable"),
    ("enabled", "disabled"),
    ("resolved", "unresolved"),
    ("true", "false"),
    ("up", "down"),
)
_GENERIC_TOKENS = {
    "available",
    "change",
    "completed",
    "deployment",
    "event",
    "failed",
    "health",
    "incident",
    "record",
    "release",
    "report",
    "service",
    "status",
    "synthetic",
}


class InvestigationState(TypedDict, total=False):
    investigation_id: str
    organization_id: str
    request: str
    simulation_scenario_id: str | None
    plan: dict[str, Any]
    evidence: list[dict[str, Any]]
    hypotheses: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    unresolved_questions: list[dict[str, Any]]
    tool_executions: list[dict[str, Any]]
    warnings: list[str]
    retrieval_mode: str
    report: dict[str, Any]


class InvestigationStageError(RuntimeError):
    def __init__(self, stage: str) -> None:
        super().__init__(f"Investigation stage {stage} failed.")
        self.stage = stage


def _stage_node(
    stage: str,
    node: Callable[[InvestigationState], dict[str, Any]],
) -> Callable[[InvestigationState], dict[str, Any]]:
    def execute(state: InvestigationState) -> dict[str, Any]:
        try:
            return node(state)
        except Exception as exc:
            raise InvestigationStageError(stage) from exc

    return execute


def _mark_task(state: InvestigationState, task_id: str) -> dict[str, Any]:
    plan = state.get("plan")
    if not plan:
        return {}
    return {
        "plan": {
            **plan,
            "tasks": [
                {
                    **task,
                    "status": "completed" if task["id"] == task_id else task["status"],
                }
                for task in plan["tasks"]
            ],
        }
    }


def intake_node(state: InvestigationState) -> dict[str, Any]:
    tasks = [
        InvestigationTask(id="retrieve_knowledge", title="Search internal knowledge"),
        InvestigationTask(id="query_operational_sources", title="Check approved operational sources"),
        InvestigationTask(id="verify_evidence", title="Verify source references and identify gaps"),
    ]
    plan = InvestigationPlan(
        objective=state["request"],
        tasks=tasks,
        max_steps=8,
    )
    return {"plan": plan.model_dump(mode="json")}


def retrieval_node(state: InvestigationState) -> dict[str, Any]:
    factory = get_session_factory()
    with factory() as session:
        result = hybrid_search(
            state["request"],
            session,
            state.get("organization_id", "local"),
            limit=8,
            simulation_scenario_id=state.get("simulation_scenario_id"),
        )
    return {
        **_mark_task(state, "retrieve_knowledge"),
        "evidence": [item.model_dump(mode="json") for item in result.evidence],
        "retrieval_mode": result.mode,
        "warnings": result.warnings,
    }


def tool_node(state: InvestigationState) -> dict[str, Any]:
    results = run_read_only_tools(
        state["request"], state.get("simulation_scenario_id")
    )
    return {
        **_mark_task(state, "query_operational_sources"),
        "tool_executions": results,
    }


def _find_conflicts(evidence: list[RetrievedEvidence]) -> list[EvidenceConflict]:
    token_sets = [
        {token.casefold() for token in _WORD.findall(item.excerpt)}
        for item in evidence
    ]
    conflicts: list[EvidenceConflict] = []
    for left_index, left in enumerate(evidence):
        for right_index in range(left_index + 1, len(evidence)):
            right = evidence[right_index]
            shared = {
                token
                for token in token_sets[left_index] & token_sets[right_index]
                if len(token) > 3 and token not in _GENERIC_TOKENS
            }
            if not shared:
                continue
            opposing = next(
                (
                    (positive, negative)
                    for positive, negative in _CONFLICT_PAIRS
                    if (
                        positive in token_sets[left_index]
                        and negative in token_sets[right_index]
                    )
                    or (
                        negative in token_sets[left_index]
                        and positive in token_sets[right_index]
                    )
                ),
                None,
            )
            if opposing is None:
                continue
            conflicts.append(
                EvidenceConflict(
                    description=(
                        f"Retrieved sources disagree: {left.metadata.get('source', left.source_id)} "
                        f"and {right.metadata.get('source', right.source_id)} contain opposing "
                        f"status terms '{opposing[0]}' and '{opposing[1]}'. Review the source records."
                    ),
                    evidence_refs=[
                        EvidenceReference(evidence_id=left.evidence_id),
                        EvidenceReference(evidence_id=right.evidence_id),
                    ],
                )
            )
    return conflicts


def analysis_node(state: InvestigationState) -> dict[str, Any]:
    evidence = [
        RetrievedEvidence.model_validate(item) for item in state.get("evidence", [])
    ]
    findings = [
        Finding(
            id=f"finding-{uuid4()}",
            statement=(
                f"Potentially relevant material was retrieved from "
                f"{item.metadata.get('source', item.source_id)}; the excerpt is "
                "provided as evidence, not proof of incident causation."
            ),
            classification=FindingClassification.possible,
            evidence_refs=[EvidenceReference(evidence_id=item.evidence_id)],
        ).model_dump(mode="json")
        for item in evidence
    ]
    conflicts = _find_conflicts(evidence)
    findings.extend(
        Finding(
            id=f"finding-{uuid4()}",
            statement=conflict.description,
            classification=FindingClassification.contradicted,
            evidence_refs=conflict.evidence_refs,
        ).model_dump(mode="json")
        for conflict in conflicts
    )
    hypotheses: list[dict[str, Any]] = []
    if evidence:
        hypotheses.append(
            {
                "id": f"hypothesis-{uuid4()}",
                "statement": (
                    "One or more retrieved sources may be relevant to the incident; "
                    "their relationship to the observed symptoms is not established."
                ),
                "classification": FindingClassification.possible.value,
                "evidence_refs": [
                    {"evidence_id": item.evidence_id} for item in evidence[:3]
                ],
                "rationale": "Retrieval relevance is not proof of truth or causation.",
            }
        )
    unresolved = [
        UnresolvedQuestion(
            question="Which deployment and log records overlap the incident window?",
            reason="Live deployment, log, and monitoring integrations are not configured.",
        ).model_dump(mode="json"),
        UnresolvedQuestion(
            question="What evidence confirms or falsifies the suspected root cause?",
            reason="No causality can be established from document similarity alone.",
        ).model_dump(mode="json"),
    ]
    if conflicts:
        unresolved.insert(
            0,
            UnresolvedQuestion(
                question="Which source is authoritative for the conflicting status?",
                reason="The retrieved records contain explicit opposing status terms.",
            ).model_dump(mode="json"),
        )
    if not evidence:
        unresolved.insert(
            0,
            UnresolvedQuestion(
                question="Which internal records describe this incident?",
                reason="No relevant knowledge-base chunks were retrieved.",
            ).model_dump(mode="json"),
        )
    return {
        **_mark_task(state, "verify_evidence"),
        "findings": findings,
        "conflicts": [item.model_dump(mode="json") for item in conflicts],
        "hypotheses": hypotheses,
        "unresolved_questions": unresolved,
    }


def verification_node(state: InvestigationState) -> dict[str, Any]:
    known_ids = {item["evidence_id"] for item in state.get("evidence", [])}
    findings = []
    for raw in state.get("findings", []):
        finding = Finding.model_validate(raw)
        if not finding.evidence_refs or any(
            reference.evidence_id not in known_ids for reference in finding.evidence_refs
        ):
            finding.classification = FindingClassification.unverified
            finding.evidence_refs = [
                reference
                for reference in finding.evidence_refs
                if reference.evidence_id in known_ids
            ]
        findings.append(finding.model_dump(mode="json"))
    return {"findings": findings}


def report_node(state: InvestigationState) -> dict[str, Any]:
    evidence = state.get("evidence", [])
    findings = state.get("findings", [])
    summary = (
        f"Investigation reviewed {len(evidence)} knowledge-base evidence item(s). "
        "No root cause is confirmed."
    )
    limitations = [
        "Similarity and keyword retrieval scores are not proof of factual accuracy.",
        "Operational integrations are simulated and returned no live deployment, log, or health data.",
        "This report does not execute remediation actions.",
    ]
    limitations.extend(state.get("warnings", []))
    return {
        "report": {
            "summary": summary,
            "findings": findings,
            "hypotheses": state.get("hypotheses", []),
            "unresolved_questions": state.get("unresolved_questions", []),
            "evidence": evidence,
            "conflicts": state.get("conflicts", []),
            "recommended_actions": [
                "Connect approved read-only deployment, incident, logging, and monitoring sources.",
                "Compare deployment and application-log timestamps for the incident window.",
                "Require a human review before any configuration or remediation change.",
            ],
            "limitations": limitations,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    }


def build_investigation_graph(checkpointer: Any | None = None):
    graph = StateGraph(InvestigationState)
    graph.add_node("intake", _stage_node("intake", intake_node))
    graph.add_node("retrieval", _stage_node("retrieval", retrieval_node))
    graph.add_node("tools", _stage_node("tools", tool_node))
    graph.add_node("analysis", _stage_node("analysis", analysis_node))
    graph.add_node("verification", _stage_node("verification", verification_node))
    graph.add_node("report", _stage_node("report", report_node))
    graph.set_entry_point("intake")
    graph.add_edge("intake", "retrieval")
    graph.add_edge("retrieval", "tools")
    graph.add_edge("tools", "analysis")
    graph.add_edge("analysis", "verification")
    graph.add_edge("verification", "report")
    graph.add_edge("report", END)
    return graph.compile(checkpointer=checkpointer)

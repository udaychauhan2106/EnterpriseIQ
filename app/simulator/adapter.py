import csv
import json
import re
from pathlib import Path
from typing import Any

from app.simulator.materialize import DEFAULT_OUTPUT_DIR, materialize_scenario
from app.simulator.scenarios import get_scenario
from app.simulator.config import load_simulation_config
from app.simulator.services import SERVICE_CATALOG

_TOKEN = re.compile(r"[a-z0-9][a-z0-9_.:/-]*", re.IGNORECASE)
_PUBLISH_ARTIFACTS = (
    "incident.json",
    "timeline.json",
    "logs/application.log",
    "logs/infrastructure.log",
    "logs/monitoring.log",
    "metrics.csv",
    "deployment_history.json",
    "technical_documentation/runbook.md",
    "reports/incident_report.md",
    "resolution.json",
)
_ARTIFACT_IDS = {
    "incident": "incident.json",
    "timeline": "timeline.json",
    "application-logs": "logs/application.log",
    "infrastructure-logs": "logs/infrastructure.log",
    "monitoring-logs": "logs/monitoring.log",
    "metrics": "metrics.csv",
    "deployments": "deployment_history.json",
    "runbook": "technical_documentation/runbook.md",
    "incident-report": "reports/incident_report.md",
    "resolution": "resolution.json",
}


def scenario_artifact_dir(scenario_id: str) -> Path:
    package = get_scenario(scenario_id)
    directory = DEFAULT_OUTPUT_DIR / scenario_id
    if not (directory / "incident.json").is_file():
        materialize_scenario(package, load_simulation_config(), DEFAULT_OUTPUT_DIR)
    return directory


def _read_json(scenario_id: str, relative_path: str) -> dict[str, Any]:
    path = scenario_artifact_dir(scenario_id) / relative_path
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("synthetic") is not True:
        raise ValueError(f"Synthetic artifact is missing its marker: {relative_path}")
    return payload


def _query_terms(query: str) -> set[str]:
    return {term.casefold() for term in _TOKEN.findall(query) if len(term) > 2}


def _matches_query(query: str, text: str) -> bool:
    terms = _query_terms(query)
    return not terms or any(term in text.casefold() for term in terms)


def incident_history(scenario_id: str, query: str = "", limit: int = 20) -> dict[str, Any]:
    incident = _read_json(scenario_id, "incident.json")
    timeline = _read_json(scenario_id, "timeline.json")
    events = [
        event
        for event in timeline["events"]
        if _matches_query(query, json.dumps(event, sort_keys=True))
    ]
    return {
        "synthetic": True,
        "incident": incident,
        "events": events[:limit],
    }


def search_logs(
    scenario_id: str,
    query: str = "",
    log_type: str = "application",
    service_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    filenames = {
        "application": "application.log",
        "infrastructure": "infrastructure.log",
        "monitoring": "monitoring.log",
    }
    if log_type not in filenames:
        raise ValueError(f"Unknown synthetic log type: {log_type}")
    path = scenario_artifact_dir(scenario_id) / "logs" / filenames[log_type]
    lines = path.read_text(encoding="utf-8").splitlines()
    matches = [
        line
        for line in lines[1:]
        if _matches_query(query, line)
        and (service_id is None or f"service={service_id} " in line)
    ]
    return {
        "synthetic": True,
        "scenario_id": scenario_id,
        "log_type": log_type,
        "records": matches[:limit],
    }


def search_application_logs(
    scenario_id: str, query: str = "", service_id: str | None = None, limit: int = 50
) -> dict[str, Any]:
    return search_logs(scenario_id, query, "application", service_id, limit)


def structured_metrics(scenario_id: str, query: str = "", limit: int = 50) -> dict[str, Any]:
    path = scenario_artifact_dir(scenario_id) / "metrics.csv"
    with path.open(encoding="utf-8", newline="") as metrics_file:
        rows = list(csv.DictReader(metrics_file))
    matches = [
        row
        for row in rows
        if _matches_query(query, json.dumps(row, sort_keys=True))
    ]
    if any(row["synthetic"].casefold() != "true" for row in matches):
        raise ValueError("Non-synthetic metric data found in a synthetic scenario.")
    return {"synthetic": True, "scenario_id": scenario_id, "records": matches[:limit]}


def deployment_history(scenario_id: str, query: str = "", limit: int = 50) -> dict[str, Any]:
    payload = _read_json(scenario_id, "deployment_history.json")
    payload["records"] = [
        record
        for record in payload["records"]
        if _matches_query(query, json.dumps(record, sort_keys=True))
    ][:limit]
    return payload


def service_health(scenario_id: str) -> dict[str, Any]:
    incident = _read_json(scenario_id, "incident.json")
    timeline = _read_json(scenario_id, "timeline.json")
    services = set(incident["affected_services"])
    observations: dict[str, list[dict[str, Any]]] = {
        service_id: [] for service_id in services
    }
    for event in timeline["events"]:
        service_id = event["service_id"]
        if service_id in services:
            observations[service_id].append(event)
    summary = []
    for service_id in incident["affected_services"]:
        service_events = observations[service_id]
        severities = {event["severity"] for event in service_events}
        latest_event = service_events[-1] if service_events else None
        observed_status = (
            "degraded_signal_observed"
            if severities & {"error", "critical"}
            else "warning_signals"
            if "warning" in severities
            else "no_failure_signal_seen"
        )
        summary.append(
            {
                "service_id": service_id,
                "service_name": SERVICE_CATALOG[service_id].name,
                "observed_status": observed_status,
                "observed_severities": sorted(severities),
                "latest_event_id": latest_event["event_id"] if latest_event else None,
                "latest_event_severity": (
                    latest_event["severity"] if latest_event else None
                ),
            }
        )
    return {
        "synthetic": True,
        "scenario_id": scenario_id,
        "source": "generated event severity; not a live health probe",
        "services": summary,
    }


def publishable_artifacts(scenario_id: str) -> tuple[tuple[str, str], ...]:
    directory = scenario_artifact_dir(scenario_id)
    artifacts: list[tuple[str, str]] = []
    for relative_path in _PUBLISH_ARTIFACTS:
        path = directory / relative_path
        if not path.is_file():
            raise FileNotFoundError(f"Expected synthetic evidence artifact is missing: {path}")
        artifacts.append((relative_path, path.read_text(encoding="utf-8")))
    return tuple(artifacts)


def scenario_evidence_manifest(scenario_id: str) -> list[dict[str, str | bool]]:
    directory = scenario_artifact_dir(scenario_id)
    return [
        {
            "artifact_id": artifact_id,
            "source": f"Nexora/{scenario_id}/{relative_path}",
            "source_type": Path(relative_path).suffix.lstrip(".") or "text",
            "available": (directory / relative_path).is_file(),
        }
        for artifact_id, relative_path in _ARTIFACT_IDS.items()
    ]


def read_scenario_artifact(scenario_id: str, artifact_id: str) -> dict[str, str | bool]:
    relative_path = _ARTIFACT_IDS.get(artifact_id)
    if relative_path is None:
        raise KeyError(artifact_id)
    artifacts = dict(publishable_artifacts(scenario_id))
    if relative_path not in artifacts:
        raise FileNotFoundError(f"Synthetic evidence artifact is unavailable: {relative_path}")
    return {
        "scenario_id": scenario_id,
        "artifact_id": artifact_id,
        "source": f"Nexora/{scenario_id}/{relative_path}",
        "source_type": Path(relative_path).suffix.lstrip(".") or "text",
        "content": artifacts[relative_path],
        "synthetic": True,
    }

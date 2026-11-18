import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.simulator.config import load_simulation_config
from app.simulator.generator import generate_incident
from app.simulator.scenarios import SCENARIO_CATALOG, ScenarioPackage, get_scenario
from app.simulator.schemas import EventSource, GeneratedEvent, SimulationConfig

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "simulator_data" / "nexora" / "generated"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _render_log_event(event: GeneratedEvent) -> str:
    correlation_id = event.correlation_id or "-"
    return (
        f"SYNTHETIC | {event.timestamp.isoformat()} | "
        f"severity={event.severity.value} | service={event.service_id} | "
        f"correlation_id={correlation_id} | {event.message}"
    )


def materialize_scenario(
    package: ScenarioPackage,
    config: SimulationConfig,
    output_dir: Path,
) -> Path:
    scenario = package.scenario
    started_at = package.started_at
    if isinstance(started_at, str):
        started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    incident = generate_incident(scenario, config, started_at)
    destination = output_dir / scenario.scenario_id

    _write_json(
        destination / "incident.json",
        {
            "synthetic": True,
            "label": "SYNTHETIC INCIDENT",
            "scenario_id": scenario.scenario_id,
            "title": scenario.title,
            "description": scenario.description,
            "difficulty": scenario.difficulty.value,
            "affected_services": list(scenario.affected_services),
            "started_at": incident.started_at.isoformat(),
            "window_ended_at": incident.ends_at.isoformat(),
            "status": package.resolution_record.get("status", "simulated"),
            "seed": incident.seed,
        },
    )
    _write_json(
        destination / "timeline.json",
        {
            "synthetic": True,
            "scenario_id": scenario.scenario_id,
            "events": [event.model_dump(mode="json") for event in incident.events],
        },
    )

    logs_dir = destination / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    event_groups = {
        "application.log": [
            event for event in incident.events if event.source == EventSource.APPLICATION_LOG
        ],
        "infrastructure.log": [
            event
            for event in incident.events
            if event.source
            in {EventSource.INFRASTRUCTURE_LOG, EventSource.PLATFORM}
        ],
        "monitoring.log": [
            event for event in incident.events if event.source == EventSource.MONITORING
        ],
    }
    for filename, events in event_groups.items():
        lines = [f"# SYNTHETIC evidence for {scenario.scenario_id}."]
        lines.extend(_render_log_event(event) for event in events)
        (logs_dir / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")

    _write_json(
        destination / "deployment_history.json",
        {
            "synthetic": True,
            "scenario_id": scenario.scenario_id,
            "records": [
                event.model_dump(mode="json")
                for event in incident.events
                if event.source == EventSource.DEPLOYMENT
            ],
        },
    )

    metrics_path = destination / "metrics.csv"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    with metrics_path.open("w", newline="", encoding="utf-8") as metrics_file:
        fieldnames = [
            "sample_id",
            "scenario_id",
            "timestamp",
            "service_id",
            "metric_name",
            "value",
            "unit",
            "synthetic",
        ]
        writer = csv.DictWriter(metrics_file, fieldnames=fieldnames)
        writer.writeheader()
        for sample in incident.metrics:
            writer.writerow(sample.model_dump(mode="json"))

    documentation_dir = destination / "technical_documentation"
    documentation_dir.mkdir(parents=True, exist_ok=True)
    (documentation_dir / "runbook.md").write_text(
        f"<!-- SYNTHETIC DOCUMENTATION for {scenario.scenario_id} -->\n"
        + package.runbook,
        encoding="utf-8",
    )
    report_dir = destination / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "incident_report.md").write_text(
        f"<!-- SYNTHETIC INCIDENT REPORT for {scenario.scenario_id} -->\n"
        + package.incident_report,
        encoding="utf-8",
    )
    _write_json(
        destination / "resolution.json",
        {
            **package.resolution_record,
            "synthetic": True,
            "scenario_id": scenario.scenario_id,
        },
    )
    return destination


def main() -> None:
    from app.simulator.ground_truth import write_ground_truth_files

    parser = argparse.ArgumentParser(
        description="Materialize reproducible synthetic Nexora incident evidence."
    )
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIO_CATALOG),
        help="Materialize one scenario; defaults to all available scenarios.",
    )
    parser.add_argument("--seed", type=int, help="Override the configured scenario seed.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for synthetic incident artifacts.",
    )
    args = parser.parse_args()
    config = load_simulation_config()
    if args.seed is not None:
        config = config.model_copy(update={"scenario_seed": args.seed})
    packages = (
        (get_scenario(args.scenario),)
        if args.scenario
        else tuple(SCENARIO_CATALOG.values())
    )
    for package in packages:
        destination = materialize_scenario(package, config, args.output_dir)
        print(f"Materialized synthetic {package.scenario.scenario_id} at {destination}")
    ground_truth_paths = write_ground_truth_files(
        args.output_dir.parent / "ground_truth",
        tuple(package.scenario.scenario_id for package in packages),
    )
    for path in ground_truth_paths:
        print(f"Wrote isolated synthetic evaluation truth at {path}")


if __name__ == "__main__":
    main()

import csv
import json
from pathlib import Path

import pytest

from app.simulator.config import load_simulation_config
from app.simulator.materialize import materialize_scenario
from app.simulator.ground_truth import GROUND_TRUTH, write_ground_truth_files
from app.simulator.scenarios import SCENARIO_CATALOG, get_scenario
from app.simulator.schemas import EventSource
from app.simulator.adapter import publishable_artifacts


def test_initial_catalog_contains_three_difficulty_tiers() -> None:
    assert set(SCENARIO_CATALOG) == {
        f"INC-{number:03}"
        for number in range(1, 11)
    }
    assert {
        package.scenario.difficulty.value
        for package in SCENARIO_CATALOG.values()
    } == {"easy", "medium", "hard"}
    assert sum(
        package.scenario.difficulty.value == "hard"
        for package in SCENARIO_CATALOG.values()
    ) >= 3
    assert all(package.scenario.synthetic for package in SCENARIO_CATALOG.values())


def test_payment_incident_has_distributed_correlated_evidence(tmp_path: Path) -> None:
    package = get_scenario("INC-001")
    destination = materialize_scenario(
        package, load_simulation_config(), tmp_path
    )

    timeline = json.loads((destination / "timeline.json").read_text(encoding="utf-8"))
    sources = {event["source"] for event in timeline["events"]}
    assert timeline["synthetic"] is True
    assert {
        EventSource.APPLICATION_LOG.value,
        EventSource.INFRASTRUCTURE_LOG.value,
        EventSource.DEPLOYMENT.value,
        EventSource.MONITORING.value,
    } <= sources

    app_log = (destination / "logs" / "application.log").read_text(encoding="utf-8")
    infra_log = (
        destination / "logs" / "infrastructure.log"
    ).read_text(encoding="utf-8")
    assert "SYNTHETIC" in app_log and "correlation_id=nexora-inc001-trace-8842" in app_log
    assert "SYNTHETIC" in infra_log and "correlation_id=nexora-inc001-trace-8842" in infra_log


def test_materialized_evidence_is_reproducible_and_excludes_ground_truth(
    tmp_path: Path,
) -> None:
    package = get_scenario("INC-002")
    config = load_simulation_config()
    first = materialize_scenario(package, config, tmp_path / "first")
    replay = materialize_scenario(package, config, tmp_path / "replay")
    expected_files = {
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
    }

    first_files = {
        path.relative_to(first).as_posix()
        for path in first.rglob("*")
        if path.is_file()
    }
    replay_files = {
        path.relative_to(replay).as_posix()
        for path in replay.rglob("*")
        if path.is_file()
    }
    assert first_files == replay_files == expected_files
    assert {
        relative: (first / relative).read_bytes()
        for relative in expected_files
    } == {
        relative: (replay / relative).read_bytes()
        for relative in expected_files
    }
    assert not any("ground_truth" in relative for relative in first_files)

    incident = json.loads((first / "incident.json").read_text(encoding="utf-8"))
    resolution = json.loads((first / "resolution.json").read_text(encoding="utf-8"))
    assert incident["synthetic"] is True
    assert resolution["synthetic"] is True
    with (first / "metrics.csv").open(encoding="utf-8", newline="") as metrics_file:
        assert all(row["synthetic"] == "True" for row in csv.DictReader(metrics_file))


@pytest.mark.parametrize("scenario_id", sorted(SCENARIO_CATALOG))
def test_every_scenario_materializes_complete_synthetic_evidence(
    scenario_id: str, tmp_path: Path
) -> None:
    config = load_simulation_config().model_copy(
        update={"service_failure_probability": 1}
    )
    destination = materialize_scenario(
        get_scenario(scenario_id), config, tmp_path / "generated"
    )
    timeline = json.loads((destination / "timeline.json").read_text(encoding="utf-8"))
    assert timeline["synthetic"] is True
    assert timeline["events"]
    assert [event["timestamp"] for event in timeline["events"]] == sorted(
        event["timestamp"] for event in timeline["events"]
    )
    assert {
        event["source"] for event in timeline["events"]
    } >= {
        EventSource.APPLICATION_LOG.value,
        EventSource.INFRASTRUCTURE_LOG.value,
        EventSource.DEPLOYMENT.value,
        EventSource.MONITORING.value,
    }
    for relative in (
        "logs/application.log",
        "logs/infrastructure.log",
        "logs/monitoring.log",
        "technical_documentation/runbook.md",
        "reports/incident_report.md",
    ):
        assert "SYNTHETIC" in (destination / relative).read_text(encoding="utf-8")


def test_ground_truth_is_written_outside_public_evidence_and_never_publishable(
    tmp_path: Path,
) -> None:
    ground_truth_dir = tmp_path / "ground_truth"
    paths = write_ground_truth_files(ground_truth_dir)
    assert len(paths) == len(GROUND_TRUTH) == 10
    for scenario_id in SCENARIO_CATALOG:
        truth_path = ground_truth_dir / scenario_id / "ground_truth.json"
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        assert truth["synthetic"] is True
        assert truth["scenario_id"] == scenario_id
        assert truth["root_cause"]
        assert truth["relevant_evidence_identifiers"]
        assert not any(
            "ground_truth" in source.casefold()
            for source, _ in publishable_artifacts(scenario_id)
        )
        public_artifacts = dict(publishable_artifacts(scenario_id))
        for identifier in truth["relevant_evidence_identifiers"]:
            assert identifier["artifact"] in public_artifacts
            assert identifier["contains"].casefold() in public_artifacts[
                identifier["artifact"]
            ].casefold()

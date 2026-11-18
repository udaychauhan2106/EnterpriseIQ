from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.simulator import (
    EventSeverity,
    EventSource,
    MetricProfile,
    ScenarioDefinition,
    ScenarioDifficulty,
    ScenarioEventSpec,
    SimulationConfig,
    generate_incident,
    load_simulation_config,
)
from app.simulator.scenarios import get_scenario


def _scenario() -> ScenarioDefinition:
    return ScenarioDefinition(
        scenario_id="INC-001",
        title="Synthetic payment dependency failure",
        description="A fictional payment incident used to test deterministic simulation.",
        difficulty=ScenarioDifficulty.EASY,
        affected_services=("payment-service", "postgresql"),
        events=(
            ScenarioEventSpec(
                offset_seconds=30,
                source=EventSource.APPLICATION_LOG,
                service_id="payment-service",
                severity=EventSeverity.ERROR,
                message="Synthetic database acquisition timeout.",
                correlation_id="trace-synthetic-001",
                failure_injection=True,
            ),
            ScenarioEventSpec(
                offset_seconds=60,
                source=EventSource.DEPLOYMENT,
                service_id="payment-service",
                message="Synthetic worker concurrency change recorded.",
            ),
        ),
        metrics=(
            MetricProfile(
                service_id="postgresql",
                metric_name="db.connection_utilization",
                unit="percent",
                baseline_value=40,
                peak_value=95,
                change_start_seconds=60,
                change_end_seconds=180,
            ),
        ),
    )


def test_same_scenario_seed_and_start_time_reproduce_identical_timeline() -> None:
    scenario = _scenario()
    config = SimulationConfig(
        incident_duration_seconds=180,
        metric_sampling_interval_seconds=60,
        service_failure_probability=1,
        scenario_seed=42,
    )
    start_time = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)

    first = generate_incident(scenario, config, start_time)
    replay = generate_incident(scenario, config, start_time)

    assert first == replay
    assert all(event.synthetic for event in first.events)
    assert all(sample.synthetic for sample in first.metrics)
    assert any(event.correlation_id == "trace-synthetic-001" for event in first.events)


def test_generated_events_are_ordered_and_metrics_cover_incident_window() -> None:
    result = generate_incident(
        _scenario(),
        SimulationConfig(
            incident_duration_seconds=180,
            event_generation_interval_seconds=30,
            metric_sampling_interval_seconds=60,
            background_noise_probability=1,
            scenario_seed=7,
        ),
        datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc),
    )

    event_times = [event.timestamp for event in result.events]
    metric_times = [sample.timestamp for sample in result.metrics]
    assert event_times == sorted(event_times)
    assert metric_times == sorted(metric_times)
    assert metric_times[0] == result.started_at
    assert metric_times[-1] == result.ends_at
    assert len(result.metrics) == 4
    assert all(result.started_at <= timestamp <= result.ends_at for timestamp in event_times)


def test_failure_probability_can_suppress_injected_failure_without_suppressing_other_events() -> None:
    result = generate_incident(
        _scenario(),
        SimulationConfig(
            incident_duration_seconds=180,
            service_failure_probability=0,
            background_noise_probability=0,
        ),
        datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc),
    )

    assert all("acquisition timeout" not in event.message for event in result.events)
    assert any("worker concurrency" in event.message for event in result.events)


def test_metrics_return_to_baseline_after_the_scenario_resolution_window() -> None:
    config = SimulationConfig(
        incident_duration_seconds=900,
        metric_sampling_interval_seconds=60,
        service_failure_probability=1,
        background_noise_probability=0,
        scenario_seed=42,
    )
    result = generate_incident(
        get_scenario("INC-001").scenario,
        config,
        datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc),
    )
    connection_samples = [
        sample
        for sample in result.metrics
        if sample.metric_name == "db.connection_utilization"
    ]
    peak_sample = next(
        sample
        for sample in connection_samples
        if sample.timestamp == result.started_at + timedelta(seconds=240)
    )

    assert connection_samples[0].value == 42
    assert peak_sample.value == 96
    assert connection_samples[-1].value == 42


def test_schema_rejects_unknown_services_and_naive_start_times() -> None:
    with pytest.raises(ValidationError, match="Unknown synthetic service"):
        ScenarioEventSpec(
            offset_seconds=1,
            source=EventSource.APPLICATION_LOG,
            service_id="real-production-database",
            message="Must not reference a real service.",
        )

    with pytest.raises(ValueError, match="timezone"):
        generate_incident(
            _scenario(),
            SimulationConfig(incident_duration_seconds=180),
            datetime(2026, 11, 18, 12, 0),
        )


def test_checked_in_simulation_config_loads() -> None:
    config = load_simulation_config()
    assert config.incident_duration_seconds == 900
    assert config.scenario_seed == 20261118

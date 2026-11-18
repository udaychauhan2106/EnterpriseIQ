import hashlib
import random
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from app.simulator.schemas import (
    EventSeverity,
    EventSource,
    GeneratedEvent,
    GeneratedIncident,
    MetricProfile,
    MetricSample,
    ScenarioDefinition,
    ScenarioEventSpec,
    SimulationConfig,
)
from app.simulator.services import SERVICE_CATALOG

_NOISE_MESSAGES = (
    "Synthetic routine health poll completed without an alert.",
    "Synthetic background request completed within the expected range.",
    "Synthetic cache refresh completed successfully.",
    "Synthetic scheduler check found no pending work.",
)


def _random_seed(scenario_id: str, scenario_seed: int) -> int:
    material = f"{scenario_id}:{scenario_seed}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def _event_id(scenario_id: str, seed: int, ordinal: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"nexora:{scenario_id}:{seed}:event:{ordinal}"))


def _create_scenario_event(
    scenario: ScenarioDefinition,
    config: SimulationConfig,
    start_time: datetime,
    spec: ScenarioEventSpec,
    ordinal: int,
    rng: random.Random,
) -> GeneratedEvent | None:
    if spec.offset_seconds > config.incident_duration_seconds:
        raise ValueError(
            f"Scenario event at {spec.offset_seconds}s exceeds the configured "
            "incident duration."
        )
    if spec.failure_injection and rng.random() >= config.service_failure_probability:
        return None
    return GeneratedEvent(
        event_id=_event_id(scenario.scenario_id, config.scenario_seed, f"scenario-{ordinal}"),
        scenario_id=scenario.scenario_id,
        timestamp=start_time + timedelta(seconds=spec.offset_seconds),
        source=spec.source,
        service_id=spec.service_id,
        severity=spec.severity,
        message=spec.message,
        correlation_id=spec.correlation_id,
        attributes=spec.attributes,
    )


def _generate_background_events(
    scenario: ScenarioDefinition,
    config: SimulationConfig,
    start_time: datetime,
    rng: random.Random,
) -> list[GeneratedEvent]:
    services = tuple(SERVICE_CATALOG)
    events: list[GeneratedEvent] = []
    for offset in range(
        config.event_generation_interval_seconds,
        config.incident_duration_seconds,
        config.event_generation_interval_seconds,
    ):
        if rng.random() >= config.background_noise_probability:
            continue
        ordinal = f"background-{offset}"
        events.append(
            GeneratedEvent(
                event_id=_event_id(scenario.scenario_id, config.scenario_seed, ordinal),
                scenario_id=scenario.scenario_id,
                timestamp=start_time + timedelta(seconds=offset),
                source=EventSource.PLATFORM,
                service_id=rng.choice(services),
                severity=EventSeverity.INFO,
                message=rng.choice(_NOISE_MESSAGES),
                attributes={"background_noise": True},
            )
        )
    return events


def _metric_value(
    profile: MetricProfile,
    offset: int,
    recovery_start: int,
    incident_duration: int,
) -> float:
    if offset <= profile.change_start_seconds:
        return profile.baseline_value
    if offset < profile.change_end_seconds:
        progress = (offset - profile.change_start_seconds) / (
            profile.change_end_seconds - profile.change_start_seconds
        )
        return profile.baseline_value + (
            profile.peak_value - profile.baseline_value
        ) * progress
    if offset <= recovery_start or recovery_start >= incident_duration:
        return profile.peak_value
    recovery_progress = (offset - recovery_start) / (
        incident_duration - recovery_start
    )
    return profile.peak_value + (
        profile.baseline_value - profile.peak_value
    ) * recovery_progress


def _generate_metrics(
    scenario: ScenarioDefinition,
    config: SimulationConfig,
    start_time: datetime,
) -> list[MetricSample]:
    samples: list[MetricSample] = []
    offsets = set(
        range(
            0,
            config.incident_duration_seconds + 1,
            config.metric_sampling_interval_seconds,
        )
    )
    offsets.add(config.incident_duration_seconds)
    recovery_start = max(
        max((event.offset_seconds for event in scenario.events), default=0),
        max((profile.change_end_seconds for profile in scenario.metrics), default=0),
    )
    for profile_index, profile in enumerate(scenario.metrics):
        if profile.change_end_seconds > config.incident_duration_seconds:
            raise ValueError(
                f"Metric profile {profile.metric_name!r} ends after the configured "
                "incident duration."
            )
        for offset in sorted(offsets):
            samples.append(
                MetricSample(
                    sample_id=_event_id(
                        scenario.scenario_id,
                        config.scenario_seed,
                        f"metric-{profile_index}-{offset}",
                    ),
                    scenario_id=scenario.scenario_id,
                    timestamp=start_time + timedelta(seconds=offset),
                    service_id=profile.service_id,
                    metric_name=profile.metric_name,
                    value=_metric_value(
                        profile,
                        offset,
                        recovery_start,
                        config.incident_duration_seconds,
                    ),
                    unit=profile.unit,
                )
            )
    return samples


def generate_incident(
    scenario: ScenarioDefinition,
    config: SimulationConfig,
    start_time: datetime,
) -> GeneratedIncident:
    """Generate a reproducible synthetic event and metric timeline."""
    if start_time.tzinfo is None or start_time.utcoffset() is None:
        raise ValueError("Simulation start_time must include a timezone.")
    start_time = start_time.astimezone(timezone.utc)
    rng = random.Random(_random_seed(scenario.scenario_id, config.scenario_seed))

    events = [
        GeneratedEvent(
            event_id=_event_id(scenario.scenario_id, config.scenario_seed, "run-start"),
            scenario_id=scenario.scenario_id,
            timestamp=start_time,
            source=EventSource.PLATFORM,
            service_id="monitoring-service",
            severity=EventSeverity.INFO,
            message=f"Synthetic simulation started for {scenario.scenario_id}.",
            attributes={"event_type": "simulation_started"},
        )
    ]
    events.extend(
        event
        for ordinal, spec in enumerate(scenario.events)
        if (
            event := _create_scenario_event(
                scenario, config, start_time, spec, ordinal, rng
            )
        )
        is not None
    )
    events.extend(_generate_background_events(scenario, config, start_time, rng))
    events.append(
        GeneratedEvent(
            event_id=_event_id(scenario.scenario_id, config.scenario_seed, "run-end"),
            scenario_id=scenario.scenario_id,
            timestamp=start_time + timedelta(seconds=config.incident_duration_seconds),
            source=EventSource.PLATFORM,
            service_id="monitoring-service",
            severity=EventSeverity.INFO,
            message=(
                f"Synthetic simulation window ended for {scenario.scenario_id}; "
                "this does not imply the incident was resolved."
            ),
            attributes={"event_type": "simulation_window_ended"},
        )
    )
    events.sort(key=lambda event: (event.timestamp, event.event_id))
    metrics = _generate_metrics(scenario, config, start_time)
    return GeneratedIncident(
        scenario_id=scenario.scenario_id,
        started_at=start_time,
        ends_at=start_time + timedelta(seconds=config.incident_duration_seconds),
        seed=config.scenario_seed,
        events=tuple(events),
        metrics=tuple(metrics),
    )

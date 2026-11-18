from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Callable
from uuid import uuid4

from app.simulator.config import load_simulation_config
from app.simulator.generator import generate_incident
from app.simulator.scenarios import get_scenario
from app.simulator.schemas import GeneratedIncident, SimulationConfig
from app.simulator.services import SERVICE_CATALOG


class SimulationRunNotFound(KeyError):
    pass


@dataclass(slots=True)
class _Run:
    run_id: str
    scenario_id: str
    seed: int
    incident: GeneratedIncident
    started_at: datetime
    resolution_offset_seconds: int
    status: str = "running"
    paused_elapsed_seconds: int = 0
    window_complete: bool = False
    replay_of: str | None = None


class SimulationRunManager:
    def __init__(
        self,
        config: SimulationConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config or load_simulation_config()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._runs: dict[str, _Run] = {}
        self._lock = RLock()

    def start(self, scenario_id: str, seed: int | None = None) -> dict:
        package = get_scenario(scenario_id)
        config = (
            self._config.model_copy(update={"scenario_seed": seed})
            if seed is not None
            else self._config
        )
        started_at = self._now()
        incident = generate_incident(package.scenario, config, started_at)
        resolution_offset = package.resolution_offset_seconds
        if resolution_offset is None:
            resolution_offset = max(
                (event.offset_seconds for event in package.scenario.events),
                default=config.incident_duration_seconds,
            )
        if resolution_offset > config.incident_duration_seconds:
            raise ValueError(
                f"Scenario resolution at {resolution_offset}s exceeds the "
                "configured incident duration."
            )
        run = _Run(
            run_id=str(uuid4()),
            scenario_id=scenario_id,
            seed=config.scenario_seed,
            incident=incident,
            started_at=started_at,
            resolution_offset_seconds=resolution_offset,
        )
        with self._lock:
            self._runs[run.run_id] = run
            return self._snapshot(run)

    def get(self, run_id: str) -> dict:
        with self._lock:
            return self._snapshot(self._get_run(run_id))

    def list(self) -> list[dict]:
        with self._lock:
            runs = sorted(
                self._runs.values(),
                key=lambda run: run.started_at,
                reverse=True,
            )
            return [self._snapshot(run, include_events=False) for run in runs]

    def stop(self, run_id: str) -> dict:
        with self._lock:
            run = self._get_run(run_id)
            elapsed = self._elapsed(run)
            if not run.window_complete:
                run.status = "stopped"
                run.paused_elapsed_seconds = elapsed
            return self._snapshot(run)

    def replay(self, run_id: str) -> dict:
        with self._lock:
            prior = self._get_run(run_id)
            replay = self.start(prior.scenario_id, prior.seed)
            self._runs[replay["run_id"]].replay_of = prior.run_id
            return self._snapshot(self._runs[replay["run_id"]])

    def remove(self, run_id: str) -> dict[str, str | bool]:
        with self._lock:
            self._get_run(run_id)
            del self._runs[run_id]
        return {"run_id": run_id, "reset": True}

    def reset(self) -> dict[str, int | bool]:
        with self._lock:
            removed = len(self._runs)
            self._runs.clear()
        return {"reset": True, "removed_runs": removed}

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Simulation clock must return a timezone-aware datetime.")
        return value.astimezone(timezone.utc)

    def _get_run(self, run_id: str) -> _Run:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise SimulationRunNotFound(run_id) from exc

    def _elapsed(self, run: _Run) -> int:
        if run.status == "stopped" or run.window_complete:
            return run.paused_elapsed_seconds
        elapsed = max(0, int((self._now() - run.started_at).total_seconds()))
        if elapsed >= run.resolution_offset_seconds:
            run.status = "resolved"
        duration = int((run.incident.ends_at - run.started_at).total_seconds())
        if elapsed >= duration:
            run.window_complete = True
            run.paused_elapsed_seconds = duration
            return duration
        return min(elapsed, duration)

    def _snapshot(self, run: _Run, include_events: bool = True) -> dict:
        elapsed = self._elapsed(run)
        visible_events = [
            event
            for event in run.incident.events
            if (event.timestamp - run.started_at).total_seconds() <= elapsed
        ]
        visible_metrics = [
            sample
            for sample in run.incident.metrics
            if (sample.timestamp - run.started_at).total_seconds() <= elapsed
        ]
        visible_severities: dict[str, set[str]] = {
            service_id: set() for service_id in SERVICE_CATALOG
        }
        latest_event: dict[str, str] = {}
        for event in visible_events:
            visible_severities[event.service_id].add(event.severity.value)
            latest_event[event.service_id] = event.event_id
        service_health = [
            {
                "service_id": service_id,
                "service_name": SERVICE_CATALOG[service_id].name,
                "observed_status": (
                    "degraded_signal_observed"
                    if severities & {"error", "critical"}
                    else "warning_signals"
                    if "warning" in severities
                    else "no_failure_signal_seen"
                ),
                "observed_severities": sorted(severities),
                "latest_event_id": latest_event.get(service_id),
            }
            for service_id in get_scenario(run.scenario_id).scenario.affected_services
            for severities in (visible_severities[service_id],)
        ]
        response = {
            "run_id": run.run_id,
            "scenario_id": run.scenario_id,
            "seed": run.seed,
            "status": run.status,
            "incident_resolved": elapsed >= run.resolution_offset_seconds,
            "elapsed_seconds": elapsed,
            "duration_seconds": int(
                (run.incident.ends_at - run.started_at).total_seconds()
            ),
            "window_complete": run.window_complete,
            "resolution_offset_seconds": run.resolution_offset_seconds,
            "started_at": run.started_at.isoformat(),
            "synthetic": True,
            "service_health_source": "generated event severity; not a live health probe",
            "service_health": service_health,
            "event_count": len(visible_events),
            "metric_count": len(visible_metrics),
            "replay_of": run.replay_of,
        }
        if include_events:
            response["events"] = [
                event.model_dump(mode="json") for event in visible_events
            ]
            response["metrics"] = [
                sample.model_dump(mode="json") for sample in visible_metrics
            ]
        return response


simulation_runs = SimulationRunManager()

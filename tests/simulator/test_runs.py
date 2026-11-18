from datetime import datetime, timedelta, timezone

import pytest

from app.simulator.config import load_simulation_config
from app.simulator.runs import SimulationRunManager, SimulationRunNotFound


class FakeClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def _manager(clock: FakeClock) -> SimulationRunManager:
    config = load_simulation_config().model_copy(
        update={
            "scenario_seed": 42,
            "background_noise_probability": 0,
            "service_failure_probability": 1,
        }
    )
    return SimulationRunManager(config=config, clock=clock)


def test_run_progresses_through_correlated_events_and_resolves() -> None:
    clock = FakeClock()
    manager = _manager(clock)
    started = manager.start("INC-008")
    assert started["status"] == "running"
    assert started["elapsed_seconds"] == 0
    assert started["synthetic"] is True
    assert started["events"]

    clock.advance(120)
    progressing = manager.get(started["run_id"])
    assert progressing["status"] == "running"
    assert progressing["elapsed_seconds"] == 120
    assert any("HTTP 404" in event["message"] for event in progressing["events"])
    assert all(
        datetime.fromisoformat(event["timestamp"]) <= clock.value
        for event in progressing["events"]
    )
    assert progressing["metrics"]
    assert progressing["service_health_source"].startswith("generated event")

    clock.advance(300)
    resolved = manager.get(started["run_id"])
    assert resolved["status"] == "resolved"
    assert resolved["elapsed_seconds"] == 420
    assert any("configuration was reverted" in event["message"] for event in resolved["events"])
    assert resolved["incident_resolved"] is True
    assert resolved["window_complete"] is False

    clock.advance(480)
    completed_window = manager.get(started["run_id"])
    ready_samples = [
        sample
        for sample in completed_window["metrics"]
        if sample["metric_name"] == "platform.ready_instances"
    ]
    assert completed_window["status"] == "resolved"
    assert completed_window["window_complete"] is True
    assert completed_window["elapsed_seconds"] == 900
    assert ready_samples[-1]["value"] == 4


def test_stop_replay_and_reset_preserve_deterministic_event_sequence() -> None:
    clock = FakeClock()
    manager = _manager(clock)
    original = manager.start("INC-006", seed=919)
    clock.advance(48)
    stopped = manager.stop(original["run_id"])
    assert stopped["status"] == "stopped"
    assert stopped["elapsed_seconds"] == 48
    clock.advance(90)
    assert manager.get(original["run_id"])["elapsed_seconds"] == 48

    replay = manager.replay(original["run_id"])
    assert replay["run_id"] != original["run_id"]
    assert replay["replay_of"] == original["run_id"]
    assert replay["seed"] == original["seed"]
    assert [event["event_id"] for event in replay["events"]] == [
        event["event_id"] for event in original["events"]
    ]

    removed = manager.remove(original["run_id"])
    assert removed == {"run_id": original["run_id"], "reset": True}
    with pytest.raises(SimulationRunNotFound):
        manager.get(original["run_id"])
    assert manager.reset()["removed_runs"] == 1
    assert manager.list() == []


def test_simulation_manager_rejects_naive_clock_values() -> None:
    manager = SimulationRunManager(clock=lambda: datetime(2026, 11, 18, 12, 0))
    with pytest.raises(ValueError, match="timezone-aware"):
        manager.start("INC-001")

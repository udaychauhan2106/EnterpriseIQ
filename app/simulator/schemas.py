from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.simulator.services import SERVICE_CATALOG


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScenarioDifficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class EventSource(StrEnum):
    APPLICATION_LOG = "application_log"
    INFRASTRUCTURE_LOG = "infrastructure_log"
    DEPLOYMENT = "deployment"
    MONITORING = "monitoring"
    PLATFORM = "platform"


class EventSeverity(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class SimulationConfig(StrictModel):
    event_generation_interval_seconds: int = Field(default=30, ge=1, le=3600)
    incident_duration_seconds: int = Field(default=900, ge=1, le=86_400)
    service_failure_probability: float = Field(default=0.85, ge=0, le=1)
    background_noise_probability: float = Field(default=0.15, ge=0, le=1)
    metric_sampling_interval_seconds: int = Field(default=60, ge=1, le=3600)
    scenario_seed: int = 20_261_118


class ScenarioEventSpec(StrictModel):
    offset_seconds: int = Field(ge=0, le=86_400)
    source: EventSource
    service_id: str
    severity: EventSeverity = EventSeverity.INFO
    message: str = Field(min_length=1, max_length=4000)
    correlation_id: str | None = Field(default=None, max_length=200)
    attributes: dict[str, Any] = Field(default_factory=dict)
    failure_injection: bool = False

    @model_validator(mode="after")
    def service_is_known(self) -> "ScenarioEventSpec":
        if self.service_id not in SERVICE_CATALOG:
            raise ValueError(f"Unknown synthetic service: {self.service_id}")
        return self


class MetricProfile(StrictModel):
    service_id: str
    metric_name: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=50)
    baseline_value: float
    peak_value: float
    change_start_seconds: int = Field(ge=0, le=86_400)
    change_end_seconds: int = Field(ge=0, le=86_400)

    @model_validator(mode="after")
    def valid_profile(self) -> "MetricProfile":
        if self.service_id not in SERVICE_CATALOG:
            raise ValueError(f"Unknown synthetic service: {self.service_id}")
        if self.change_end_seconds <= self.change_start_seconds:
            raise ValueError("Metric change_end_seconds must be after change_start_seconds.")
        return self


class ScenarioDefinition(StrictModel):
    scenario_id: str = Field(pattern=r"^INC-\d{3}$")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    difficulty: ScenarioDifficulty
    affected_services: tuple[str, ...] = Field(min_length=1)
    events: tuple[ScenarioEventSpec, ...] = ()
    metrics: tuple[MetricProfile, ...] = ()
    synthetic: Literal[True] = True

    @model_validator(mode="after")
    def all_services_are_known(self) -> "ScenarioDefinition":
        unknown = set(self.affected_services) - set(SERVICE_CATALOG)
        if unknown:
            raise ValueError(f"Unknown affected services: {', '.join(sorted(unknown))}")
        return self


class ScenarioPackage(StrictModel):
    scenario: ScenarioDefinition
    started_at: datetime
    resolution_offset_seconds: int | None = Field(default=None, ge=0, le=86_400)
    runbook: str = Field(min_length=1)
    incident_report: str = Field(min_length=1)
    resolution_record: dict[str, Any]

    @model_validator(mode="after")
    def start_time_is_aware(self) -> "ScenarioPackage":
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ValueError("Scenario start time must include a timezone.")
        return self


class GeneratedEvent(StrictModel):
    event_id: str
    scenario_id: str
    timestamp: datetime
    source: EventSource
    service_id: str
    severity: EventSeverity
    message: str
    correlation_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    synthetic: Literal[True] = True


class MetricSample(StrictModel):
    sample_id: str
    scenario_id: str
    timestamp: datetime
    service_id: str
    metric_name: str
    value: float
    unit: str
    synthetic: Literal[True] = True


class GeneratedIncident(StrictModel):
    scenario_id: str
    started_at: datetime
    ends_at: datetime
    seed: int
    events: tuple[GeneratedEvent, ...]
    metrics: tuple[MetricSample, ...]
    synthetic: Literal[True] = True

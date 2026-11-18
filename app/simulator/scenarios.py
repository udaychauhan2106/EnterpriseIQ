from types import MappingProxyType
from typing import Mapping

from app.simulator.additional_scenarios import ADDITIONAL_PACKAGES
from app.simulator.schemas import (
    EventSeverity,
    EventSource,
    MetricProfile,
    ScenarioDefinition,
    ScenarioDifficulty,
    ScenarioEventSpec,
    ScenarioPackage,
)


_PACKAGES = (
    ScenarioPackage(
        scenario=ScenarioDefinition(
            scenario_id="INC-001",
            title="Payment API connection failures",
            description=(
                "Synthetic payment API errors with database and deployment evidence "
                "distributed across independent sources."
            ),
            difficulty=ScenarioDifficulty.EASY,
            affected_services=("api-gateway", "payment-service", "postgresql"),
            events=(
                ScenarioEventSpec(
                    offset_seconds=0,
                    source=EventSource.DEPLOYMENT,
                    service_id="payment-service",
                    message=(
                        "Synthetic payment-service release 42 completed; worker "
                        "concurrency changed from 20 to 60."
                    ),
                    correlation_id="nexora-inc001-deploy-42",
                ),
                ScenarioEventSpec(
                    offset_seconds=120,
                    source=EventSource.APPLICATION_LOG,
                    service_id="payment-service",
                    severity=EventSeverity.ERROR,
                    message=(
                        "Synthetic charge request returned HTTP 500 after database "
                        "connection acquisition timed out."
                    ),
                    correlation_id="nexora-inc001-trace-8842",
                    failure_injection=True,
                ),
                ScenarioEventSpec(
                    offset_seconds=180,
                    source=EventSource.INFRASTRUCTURE_LOG,
                    service_id="postgresql",
                    severity=EventSeverity.WARNING,
                    message=(
                        "Synthetic database active connections reached 96 of 100; "
                        "connection waiters increased."
                    ),
                    correlation_id="nexora-inc001-trace-8842",
                ),
                ScenarioEventSpec(
                    offset_seconds=240,
                    source=EventSource.MONITORING,
                    service_id="api-gateway",
                    severity=EventSeverity.WARNING,
                    message=(
                        "Synthetic API error rate and p95 request latency rose "
                        "during the payment-service incident window."
                    ),
                    correlation_id="nexora-inc001-trace-8842",
                ),
                ScenarioEventSpec(
                    offset_seconds=600,
                    source=EventSource.DEPLOYMENT,
                    service_id="payment-service",
                    message=(
                        "Synthetic worker concurrency rollback recorded; "
                        "post-change connection utilization is being observed."
                    ),
                    correlation_id="nexora-inc001-deploy-rollback",
                ),
            ),
            metrics=(
                MetricProfile(
                    service_id="postgresql",
                    metric_name="db.connection_utilization",
                    unit="percent",
                    baseline_value=42,
                    peak_value=96,
                    change_start_seconds=60,
                    change_end_seconds=240,
                ),
                MetricProfile(
                    service_id="api-gateway",
                    metric_name="http.5xx_rate",
                    unit="percent",
                    baseline_value=0.2,
                    peak_value=12.4,
                    change_start_seconds=90,
                    change_end_seconds=300,
                ),
                MetricProfile(
                    service_id="api-gateway",
                    metric_name="http.p95_latency",
                    unit="milliseconds",
                    baseline_value=180,
                    peak_value=4200,
                    change_start_seconds=90,
                    change_end_seconds=360,
                ),
            ),
        ),
        started_at="2026-06-15T10:00:00Z",
        runbook=(
            "# Synthetic payment database pool runbook\n\n"
            "Check database connection utilization, acquisition wait time, active "
            "transactions, and payment request latency over the same interval. "
            "Compare worker concurrency and pool limits before changing either. "
            "Trace requests by correlation ID. A high connection count alone does "
            "not establish which service exhausted the pool. Recommended baseline "
            "for this fictional environment: 20 payment workers and a 100-connection "
            "database limit. Escalate if waiters persist after traffic normalizes.\n"
        ),
        incident_report=(
            "# Synthetic incident report: INC-001\n\n"
            "Payment API 5xx responses and database connection waiters occurred "
            "during the same window. Worker concurrency was rolled back and the "
            "service was observed afterward. The public report does not declare a "
            "confirmed root cause; correlate the independent logs, deployment "
            "history, and metrics before concluding.\n"
        ),
        resolution_record={
            "record_type": "synthetic_resolution",
            "status": "resolved",
            "actions": [
                "Returned payment worker concurrency to the prior value.",
                "Observed connection waiters and API latency until they declined.",
            ],
            "synthetic": True,
        },
    ),
    ScenarioPackage(
        scenario=ScenarioDefinition(
            scenario_id="INC-002",
            title="Authentication token validation failures",
            description=(
                "Synthetic authentication failures involving signing-key metadata, "
                "deployment history, and noisy gateway responses."
            ),
            difficulty=ScenarioDifficulty.MEDIUM,
            affected_services=(
                "api-gateway",
                "authentication-service",
                "redis",
                "postgresql",
            ),
            events=(
                ScenarioEventSpec(
                    offset_seconds=0,
                    source=EventSource.DEPLOYMENT,
                    service_id="authentication-service",
                    message=(
                        "Synthetic auth-service key rotation job started; key "
                        "identifier key-nx-2025-02 remains in the active-key list."
                    ),
                    correlation_id="nexora-inc002-rotation-17",
                ),
                ScenarioEventSpec(
                    offset_seconds=180,
                    source=EventSource.APPLICATION_LOG,
                    service_id="authentication-service",
                    severity=EventSeverity.WARNING,
                    message=(
                        "Synthetic token validation rejected key identifier "
                        "key-nx-2025-02; signing metadata reports not-after "
                        "2026-06-15T10:02:00Z."
                    ),
                    correlation_id="nexora-inc002-trace-119",
                    failure_injection=True,
                ),
                ScenarioEventSpec(
                    offset_seconds=240,
                    source=EventSource.APPLICATION_LOG,
                    service_id="api-gateway",
                    severity=EventSeverity.WARNING,
                    message=(
                        "Synthetic protected API requests returned HTTP 401; "
                        "public health checks remain successful."
                    ),
                    correlation_id="nexora-inc002-trace-119",
                ),
                ScenarioEventSpec(
                    offset_seconds=300,
                    source=EventSource.INFRASTRUCTURE_LOG,
                    service_id="redis",
                    severity=EventSeverity.INFO,
                    message=(
                        "Synthetic authentication cache hit rate decreased; Redis "
                        "latency and availability remain within baseline."
                    ),
                    correlation_id="nexora-inc002-cache-check",
                ),
                ScenarioEventSpec(
                    offset_seconds=360,
                    source=EventSource.MONITORING,
                    service_id="api-gateway",
                    severity=EventSeverity.WARNING,
                    message=(
                        "Synthetic monitoring recorded a rise in protected-route "
                        "401 responses while public readiness checks remained green."
                    ),
                    correlation_id="nexora-inc002-trace-119",
                ),
                ScenarioEventSpec(
                    offset_seconds=540,
                    source=EventSource.DEPLOYMENT,
                    service_id="authentication-service",
                    message=(
                        "Synthetic key metadata refresh completed; token validation "
                        "error counts are being monitored."
                    ),
                    correlation_id="nexora-inc002-key-refresh",
                ),
            ),
            metrics=(
                MetricProfile(
                    service_id="api-gateway",
                    metric_name="http.401_rate",
                    unit="percent",
                    baseline_value=1.1,
                    peak_value=38,
                    change_start_seconds=120,
                    change_end_seconds=300,
                ),
                MetricProfile(
                    service_id="authentication-service",
                    metric_name="token.validation_failures",
                    unit="events_per_minute",
                    baseline_value=2,
                    peak_value=185,
                    change_start_seconds=120,
                    change_end_seconds=360,
                ),
                MetricProfile(
                    service_id="redis",
                    metric_name="cache.p95_latency",
                    unit="milliseconds",
                    baseline_value=4,
                    peak_value=5,
                    change_start_seconds=120,
                    change_end_seconds=360,
                ),
            ),
        ),
        started_at="2026-06-15T10:00:00Z",
        runbook=(
            "# Synthetic authentication signing-key runbook\n\n"
            "Compare token `kid`, active signing-key metadata, validity intervals, "
            "and rotation-job output. Check gateway 401 rates separately from "
            "service health probes. Confirm cache contents and key distribution "
            "across auth instances before attributing failures to Redis. Never "
            "write private signing material to incident logs. Coordinate key "
            "rotation and token re-issuance with the identity owner.\n"
        ),
        incident_report=(
            "# Synthetic incident report: INC-002\n\n"
            "Protected requests experienced elevated 401 responses while public "
            "health checks remained successful. Key metadata refresh was recorded "
            "before the error rate returned toward baseline. Cache latency stayed "
            "near its normal range. The public report leaves causality unconfirmed.\n"
        ),
        resolution_record={
            "record_type": "synthetic_resolution",
            "status": "resolved",
            "actions": [
                "Refreshed the active signing-key metadata across auth instances.",
                "Monitored token validation and gateway 401 rates after refresh.",
            ],
            "synthetic": True,
        },
    ),
    ScenarioPackage(
        scenario=ScenarioDefinition(
            scenario_id="INC-003",
            title="Delayed notification delivery",
            description=(
                "Synthetic notification delays with queue, consumer, and downstream "
                "service evidence, including incomplete historical comparisons."
            ),
            difficulty=ScenarioDifficulty.HARD,
            affected_services=(
                "notification-service",
                "message-queue",
                "redis",
                "monitoring-service",
            ),
            events=(
                ScenarioEventSpec(
                    offset_seconds=0,
                    source=EventSource.DEPLOYMENT,
                    service_id="notification-service",
                    message=(
                        "Synthetic notification-service deployment recorded; "
                        "consumer concurrency changed from 8 to 2."
                    ),
                    correlation_id="nexora-inc003-deploy-31",
                ),
                ScenarioEventSpec(
                    offset_seconds=240,
                    source=EventSource.APPLICATION_LOG,
                    service_id="notification-service",
                    severity=EventSeverity.WARNING,
                    message=(
                        "Synthetic notification delivery age exceeded 6 minutes; "
                        "message accepted but no delivery receipt was observed."
                    ),
                    correlation_id="nexora-inc003-msg-771",
                    failure_injection=True,
                ),
                ScenarioEventSpec(
                    offset_seconds=360,
                    source=EventSource.INFRASTRUCTURE_LOG,
                    service_id="message-queue",
                    severity=EventSeverity.WARNING,
                    message=(
                        "Synthetic queue depth is rising; oldest unacknowledged "
                        "message age increased while broker nodes remained healthy."
                    ),
                    correlation_id="nexora-inc003-msg-771",
                ),
                ScenarioEventSpec(
                    offset_seconds=480,
                    source=EventSource.MONITORING,
                    service_id="monitoring-service",
                    severity=EventSeverity.INFO,
                    message=(
                        "Synthetic message-queue node health is green; consumer "
                        "acknowledgement lag is not included in the default dashboard."
                    ),
                    correlation_id="nexora-inc003-monitor-12",
                ),
                ScenarioEventSpec(
                    offset_seconds=660,
                    source=EventSource.APPLICATION_LOG,
                    service_id="notification-service",
                    severity=EventSeverity.ERROR,
                    message=(
                        "Synthetic retry worker reported intermittent Redis "
                        "timeouts for a subset of notification attempts."
                    ),
                    correlation_id="nexora-inc003-msg-812",
                ),
                ScenarioEventSpec(
                    offset_seconds=780,
                    source=EventSource.DEPLOYMENT,
                    service_id="notification-service",
                    message=(
                        "Synthetic consumer concurrency restored to 8; queue age "
                        "and delivery receipts are being checked."
                    ),
                    correlation_id="nexora-inc003-deploy-rollback",
                ),
            ),
            metrics=(
                MetricProfile(
                    service_id="message-queue",
                    metric_name="queue.depth",
                    unit="messages",
                    baseline_value=120,
                    peak_value=18_400,
                    change_start_seconds=120,
                    change_end_seconds=660,
                ),
                MetricProfile(
                    service_id="notification-service",
                    metric_name="notification.delivery_age_p95",
                    unit="seconds",
                    baseline_value=18,
                    peak_value=520,
                    change_start_seconds=180,
                    change_end_seconds=720,
                ),
                MetricProfile(
                    service_id="redis",
                    metric_name="cache.timeout_rate",
                    unit="percent",
                    baseline_value=0.1,
                    peak_value=2.8,
                    change_start_seconds=480,
                    change_end_seconds=720,
                ),
            ),
        ),
        started_at="2026-06-15T10:00:00Z",
        runbook=(
            "# Synthetic notification queue runbook\n\n"
            "Inspect queue depth, oldest-message age, consumer acknowledgement "
            "rate, and notification delivery receipts together. Broker node health "
            "does not measure consumer throughput. Compare consumer concurrency "
            "changes with backlog growth. Check Redis timeouts as a possible "
            "contributor, and compare the affected message IDs across service logs. "
            "Historical dashboards may omit acknowledgement lag; missing metrics "
            "must be reported as unknown rather than treated as zero.\n"
        ),
        incident_report=(
            "# Synthetic incident report: INC-003\n\n"
            "Notification delivery age and queue depth increased during the "
            "observation window. Broker health remained green, while a later "
            "application log mentioned intermittent Redis timeouts. Consumer "
            "concurrency was restored and delivery receipts were monitored. "
            "Evidence is incomplete and the public report does not establish "
            "which signal was primary.\n"
        ),
        resolution_record={
            "record_type": "synthetic_resolution",
            "status": "resolved",
            "actions": [
                "Restored notification consumer concurrency to the prior setting.",
                "Monitored queue age and delivery receipts until backlog declined.",
                "Scheduled a review of consumer-lag dashboard coverage.",
            ],
            "synthetic": True,
        },
    ),
)

SCENARIO_CATALOG: Mapping[str, ScenarioPackage] = MappingProxyType(
    {
        package.scenario.scenario_id: package
        for package in (*_PACKAGES, *ADDITIONAL_PACKAGES)
    }
)


def get_scenario(scenario_id: str) -> ScenarioPackage:
    try:
        return SCENARIO_CATALOG[scenario_id]
    except KeyError as exc:
        raise KeyError(f"Unknown synthetic incident scenario: {scenario_id}") from exc

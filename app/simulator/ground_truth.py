import json
from pathlib import Path
from typing import Any


EVALUATION_QUESTIONS = (
    "What caused the incident?",
    "When did the first symptom occur?",
    "Which deployment preceded the failure?",
    "Which services were affected?",
    "What evidence supports the root-cause hypothesis?",
    "What alternative explanations were considered?",
    "Which evidence contradicts the initial hypothesis?",
    "What corrective actions are appropriate?",
)


def _record(
    root_cause: str,
    keywords: tuple[str, ...],
    factors: tuple[str, ...],
    timeline: tuple[tuple[int, str], ...],
    evidence: tuple[tuple[str, str], ...],
    findings: tuple[str, ...],
    misleading: tuple[str, ...],
    hypotheses: tuple[str, ...],
    actions: tuple[str, ...],
    resolution: str,
) -> dict[str, Any]:
    return {
        "synthetic": True,
        "root_cause": root_cause,
        "root_cause_keywords": list(keywords),
        "contributing_factors": list(factors),
        "expected_timeline": [
            {"offset_seconds": offset, "event": event} for offset, event in timeline
        ],
        "relevant_evidence_identifiers": [
            {"artifact": artifact, "contains": clue} for artifact, clue in evidence
        ],
        "expected_findings": list(findings),
        "misleading_evidence": list(misleading),
        "acceptable_hypotheses": list(hypotheses),
        "corrective_actions": list(actions),
        "resolution_details": resolution,
    }


GROUND_TRUTH: dict[str, dict[str, Any]] = {
    "INC-001": _record(
        "Payment worker concurrency was raised beyond the safe database pool capacity, exhausting PostgreSQL connections.",
        ("worker concurrency", "connection pool", "connection acquisition"),
        ("Worker count increased from 20 to 60.", "The database limit remained 100 connections."),
        ((0, "Payment worker concurrency deployment"), (120, "Payment connection acquisition timeout"), (180, "Database connections near the configured maximum"), (240, "API errors and latency rise"), (600, "Concurrency rollback")),
        (("deployment_history.json", "concurrency changed from 20 to 60"), ("logs/application.log", "connection acquisition timed out"), ("logs/infrastructure.log", "96 of 100"), ("metrics.csv", "db.connection_utilization")),
        ("Payment 5xx responses followed increased worker concurrency.", "Database connection utilization rose with API latency."),
        ("Routine traffic spike", "Database fault", "Redis contention"),
        ("Traffic volume may contribute but does not explain the measured pool waiters.", "Redis contention is not supported by direct evidence."),
        ("Restore safe worker concurrency.", "Tune pool and concurrency together.", "Alert on acquisition waiters and connection saturation."),
        "Worker concurrency was rolled back and connection utilization and API latency were observed until they declined.",
    ),
    "INC-002": _record(
        "Authentication instances continued using an expired signing key after key rotation metadata became stale.",
        ("expired signing key", "key identifier", "token validation"),
        ("Key rotation metadata refresh lagged.", "Gateway health probes do not exercise protected token validation."),
        ((0, "Key rotation starts"), (180, "Token validation rejects the key identifier"), (240, "Protected API requests return 401"), (300, "Redis remains within baseline"), (540, "Key metadata refresh")),
        (("logs/application.log", "not-after"), ("deployment_history.json", "key rotation"), ("metrics.csv", "token.validation_failures"), ("logs/infrastructure.log", "latency and availability remain within baseline")),
        ("Protected 401s aligned with key validity metadata.", "Redis measurements do not support cache outage as the primary cause."),
        ("Redis cache outage", "Gateway health-check failure", "Invalid client credentials"),
        ("Stable Redis latency contradicts a broad cache outage.", "Public health checks remain successful."),
        ("Refresh active signing-key metadata on all instances.", "Verify key validity and token kid distribution.", "Monitor 401 rates after rotation."),
        "Active key metadata was refreshed and token validation errors were monitored.",
    ),
    "INC-003": _record(
        "Notification consumer concurrency was reduced, causing queue backlog and delayed delivery.",
        ("consumer concurrency", "queue depth", "delivery age"),
        ("Default dashboard omitted acknowledgement lag.", "Later Redis timeouts were limited and not the initial symptom."),
        ((0, "Consumer concurrency reduced from 8 to 2"), (240, "Notification delivery age increases"), (360, "Queue depth rises"), (480, "Broker health is green but lag is not shown"), (660, "Redis timeout noise"), (780, "Concurrency restored")),
        (("deployment_history.json", "concurrency changed from 8 to 2"), ("logs/application.log", "delivery age exceeded"), ("logs/infrastructure.log", "oldest unacknowledged"), ("metrics.csv", "queue.depth")),
        ("Delivery age and queue depth rose after the concurrency change.", "Green broker health did not establish healthy consumer throughput."),
        ("Redis timeouts", "Broker node failure", "Traffic spike"),
        ("Redis timeouts appeared after initial delivery delays.", "Broker nodes remained healthy."),
        ("Restore consumer concurrency.", "Track consumer acknowledgement lag.", "Monitor delivery receipts and oldest-message age."),
        "Consumer concurrency was restored and queue age and delivery receipts were monitored.",
    ),
    "INC-004": _record(
        "A checkout-history query-plan regression introduced inefficient database scans and elevated API latency.",
        ("query plan", "sequential scan", "database read"),
        ("The changed endpoint shipped in release 45.", "A brief cache hit-ratio dip was coincident but not sustained."),
        ((0, "Release 45 deploys checkout history change"), (150, "Query duration rises"), (210, "Database read I/O and scans increase"), (270, "API p95 latency increases"), (390, "Brief cache refresh noise"), (660, "Query change rollback")),
        (("deployment_history.json", "release 45"), ("logs/application.log", "query duration rose"), ("logs/infrastructure.log", "sequential scan counts"), ("metrics.csv", "db.read_iops")),
        ("API latency coincided with query duration and database read I/O.", "Connection utilization remained near baseline."),
        ("Connection pool exhaustion", "Cache refresh", "Gateway CPU saturation"),
        ("Connection use and gateway CPU remained near baseline.", "The cache dip was brief."),
        ("Roll back the query-plan change.", "Review query plans under representative load.", "Monitor query duration and database read I/O."),
        "The query-plan change was rolled back and endpoint latency was compared with the prior release.",
    ),
    "INC-005": _record(
        "Intermittent timeouts from the external simulated payment gateway exceeded the checkout downstream deadline.",
        ("payment gateway", "downstream deadline", "dependency latency"),
        ("Retries increased for some requests.", "Provider-side telemetry was incomplete."),
        ((0, "Release 46 recorded"), (120, "Checkout downstream deadline exceeded"), (180, "Dependency probe latency increases"), (240, "Database remains within baseline"), (330, "Gateway retries increase"), (690, "Timeout budget adjusted")),
        (("logs/application.log", "downstream request deadline"), ("logs/infrastructure.log", "payment gateway response time"), ("metrics.csv", "dependency.payment_gateway_p95"), ("logs/infrastructure.log", "connection use and commit latency remain within the usual range")),
        ("Payment dependency latency and checkout timeout rates increased.", "PostgreSQL commit timing remained near baseline."),
        ("Database slow commits", "Redis outage", "Application release regression"),
        ("Database and release evidence do not account for the external dependency latency samples."),
        ("Bound retries and align deadlines.", "Confirm provider health using request IDs.", "Reconcile timed-out attempts before retry."),
        "The timeout budget was adjusted and downstream retry volume was observed.",
    ),
    "INC-006": _record(
        "Release 52 introduced a notification-worker memory leak that accumulated over time and caused container restarts.",
        ("release 52", "heap", "memory growth", "rollback"),
        ("Memory symptoms were delayed.", "A concurrent Redis expiration wave was a plausible but separate signal."),
        ((0, "Release 52 changes worker runtime"), (180, "Post-collection heap trend rises"), (300, "Container working set increases"), (420, "Worker restarts at memory limit"), (510, "Redis expiration noise"), (600, "Garbage-collection pauses rise"), (780, "Release rollback")),
        (("deployment_history.json", "release 52"), ("logs/application.log", "heap-after-collection"), ("logs/infrastructure.log", "crossing its memory limit"), ("metrics.csv", "container.memory_working_set")),
        ("Post-collection worker heap grew after the release.", "Worker restarts aligned with memory-limit crossings."),
        ("Redis cache growth", "Traffic spike", "Worker backlog"),
        ("CPU and request volume stayed stable; Redis growth was separately scoped.", "The backlog briefly drained after restart rather than preceding memory growth."),
        ("Roll back release 52.", "Compare allocation profiles in a safe environment.", "Alert on post-collection heap growth."),
        "Release 52 was rolled back and new worker instances were checked for repeated heap growth.",
    ),
    "INC-007": _record(
        "The changed payment retry path lacked idempotency protection, allowing a repeated checkout request to commit a second transaction.",
        ("idempotency", "same order", "two committed transaction"),
        ("Delayed responses prompted client retries.", "Queue redelivery also occurred but involved different transaction references."),
        ((0, "Release 61 changes retry handling"), (120, "Same order reference retried"), (180, "No idempotency token recorded"), (240, "Two ledger rows committed"), (300, "Duplicate-transaction alert"), (390, "Separate receipt redelivery"), (720, "Retry path paused")),
        (("logs/application.log", "no idempotency-token field"), ("logs/infrastructure.log", "two committed transaction rows"), ("logs/application.log", "client retry reused order reference"), ("deployment_history.json", "retry handling was changed")),
        ("Two ledger commits share one simulated order reference.", "Retry handling changed before the duplicate transaction alert."),
        ("Duplicate receipt delivery", "Slow database commits", "Client double-submit"),
        ("The duplicate receipt refers to separate transactions and does not explain two ledger commits for one order.", "Client retry timing alone does not provide transaction deduplication."),
        ("Pause the changed retry path.", "Reconcile ledger records through the approved finance workflow.", "Apply and test stable transaction-level idempotency."),
        "The retry path was paused while transaction reconciliation and a guarded idempotency change were prepared.",
    ),
    "INC-008": _record(
        "The readiness probe targeted an unimplemented path, causing healthy authentication instances to be removed from service.",
        ("readiness probe", "/readyz", "/healthz"),
        ("A separate public health route remained healthy.", "Probe failure was treated as readiness failure rather than process failure."),
        ((0, "Probe path changed to /readyz"), (60, "Readiness probe receives 404"), (120, "Gateway 503s while /healthz returns 200"), (180, "Application listener accepts requests"), (240, "Orchestrator removes instance"), (420, "Probe configuration reverted")),
        (("deployment_history.json", "readiness probe path"), ("logs/infrastructure.log", "HTTP 404 from /readyz"), ("logs/monitoring.log", "public /healthz check returned 200"), ("metrics.csv", "platform.ready_instances")),
        ("Probe failures removed instances despite healthy application responses.", "The probe endpoint change preceded the availability loss."),
        ("Application process crash", "Gateway outage", "Authentication dependency failure"),
        ("The listener and /healthz responded successfully.", "Evidence shows probe failures rather than a process crash."),
        ("Restore the documented readiness endpoint.", "Test liveness and readiness independently.", "Monitor ready instances and gateway 503 rates."),
        "Probe configuration was reverted and authentication instances rejoined service.",
    ),
    "INC-009": _record(
        "Policy bundle 17 used an overly broad resource selector that granted a support-role identity unintended access.",
        ("policy bundle 17", "resource selector", "support-role", "authorization"),
        ("Policy-cache refresh caused unrelated denials.", "Token authentication succeeded and was not itself misconfigured."),
        ((0, "Policy bundle 17 published"), (90, "Support-role identity accesses protected route"), (150, "Restricted dataset read audited"), (210, "Token valid; role claims differ"), (270, "Unrelated denials rise during cache refresh"), (390, "Evaluator matches broad selector"), (600, "Policy bundle withdrawn")),
        (("deployment_history.json", "policy bundle 17"), ("logs/infrastructure.log", "restricted support dataset"), ("logs/infrastructure.log", "broader resource selector"), ("logs/application.log", "token signature and expiry checks passed")),
        ("A valid support-role identity received access to a restricted resource after the policy update.", "Authentication was successful; the issue was authorization scope."),
        ("Invalid token", "Credential compromise", "Policy cache outage"),
        ("Token checks passed.", "Cache-refresh denials explain some unrelated symptoms, not the unintended grant."),
        ("Withdraw the overbroad policy.", "Review access records.", "Narrow selectors and validate least-privilege tests."),
        "Policy bundle 17 was withdrawn and affected synthetic access records were reviewed.",
    ),
    "INC-010": _record(
        "The consumer advanced committed offsets before confirming destination writes, leaving source events unsynchronized.",
        ("committed offset", "sink confirmation", "checkpoint", "consumer"),
        ("Aggregate lag dashboard omitted per-partition acknowledgements.", "A transient database timeout was a contributing retry signal, not the offset-ordering defect."),
        ((0, "Consumer release 33 changes checkpoint batching"), (150, "Offset advances with fewer sink confirmations"), (240, "Destination misses source event identifiers"), (300, "Aggregate lag appears near zero"), (390, "Transient sink timeout lacks replay audit"), (510, "Checkpoint advances across unconfirmed range"), (780, "Checkpoint paused for bounded replay")),
        (("deployment_history.json", "checkpoint batching change"), ("logs/application.log", "sink confirmation count"), ("logs/infrastructure.log", "missing several source event identifiers"), ("metrics.csv", "sync.sink_confirmation_gap")),
        ("Committed offset advanced before destination confirmation.", "Low aggregate consumer lag did not prove synchronization completed."),
        ("Broker outage", "Destination table corruption", "Transient database timeout alone"),
        ("Broker nodes remained healthy.", "The timeout alone does not explain the checkpoint advancing without confirmation."),
        ("Pause checkpoint advancement.", "Reconcile missing source IDs.", "Replay from a verified sink position and add partition acknowledgement metrics."),
        "Checkpoint advancement was paused for reconciliation and bounded replay from the last verified sink position.",
    ),
}

_AFFECTED_SERVICES = {
    "INC-001": ("api-gateway", "payment-service", "postgresql"),
    "INC-002": ("api-gateway", "authentication-service", "redis", "postgresql"),
    "INC-003": ("notification-service", "message-queue", "redis", "monitoring-service"),
    "INC-004": ("api-gateway", "payment-service", "postgresql", "redis"),
    "INC-005": ("api-gateway", "payment-service", "postgresql", "monitoring-service"),
    "INC-006": ("api-gateway", "notification-service", "redis", "monitoring-service"),
    "INC-007": ("api-gateway", "payment-service", "postgresql", "message-queue"),
    "INC-008": ("api-gateway", "authentication-service", "monitoring-service"),
    "INC-009": ("api-gateway", "authentication-service", "postgresql"),
    "INC-010": ("message-queue", "postgresql", "monitoring-service"),
}


def write_ground_truth_files(
    output_dir: Path, scenario_ids: tuple[str, ...] | None = None
) -> tuple[Path, ...]:
    selected_ids = scenario_ids or tuple(GROUND_TRUTH)
    paths: list[Path] = []
    for scenario_id in selected_ids:
        record = GROUND_TRUTH[scenario_id]
        path = output_dir / scenario_id / "ground_truth.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "scenario_id": scenario_id,
                    **record,
                    "affected_services": list(_AFFECTED_SERVICES[scenario_id]),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        paths.append(path)
    return tuple(paths)

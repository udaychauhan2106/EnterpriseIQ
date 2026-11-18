import re

from app.domain.models import FindingClassification


def test_investigation_lifecycle_is_durable_and_evidence_cited(api_client) -> None:
    uploaded = api_client.post(
        "/api/v1/knowledge/documents",
        files={
            "file": (
                "payment-incident.md",
                b"Payment API returned intermittent HTTP 500 errors after deployment release 42.",
                "text/markdown",
            )
        },
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["chunk_count"] == 1
    assert uploaded.json()["version"] == 1
    status = api_client.get(
        f"/api/v1/knowledge/documents/{uploaded.json()['document_id']}"
    )
    assert status.status_code == 200
    assert status.json()["status"] == "indexed"

    created = api_client.post(
        "/api/v1/investigations",
        json={"request": "Investigate payment API 500 errors after release 42."},
    )
    assert created.status_code == 202
    investigation_id = created.json()["id"]

    detail = api_client.get(f"/api/v1/investigations/{investigation_id}")
    assert detail.status_code == 200
    investigation = detail.json()
    assert investigation["status"] == "completed"
    assert investigation["plan"]["tasks"]
    assert all(task["status"] == "completed" for task in investigation["plan"]["tasks"])
    assert len(investigation["tool_executions"]) == 5

    report_response = api_client.get(
        f"/api/v1/investigations/{investigation_id}/report"
    )
    assert report_response.status_code == 200
    report = report_response.json()
    evidence_ids = {item["evidence_id"] for item in report["evidence"]}
    assert evidence_ids
    for finding in report["findings"]:
        assert finding["classification"] != FindingClassification.confirmed.value
        assert finding["evidence_refs"]
        assert all(ref["evidence_id"] in evidence_ids for ref in finding["evidence_refs"])
    assert "No root cause is confirmed." in report["summary"]

    events = api_client.get(f"/api/v1/investigations/{investigation_id}/events")
    assert events.status_code == 200
    assert {event["event_type"] for event in events.json()} >= {
        "queued",
        "started",
        "intake",
        "retrieval",
        "tools",
        "analysis",
        "verification",
        "report",
    }


def test_upload_deduplication_and_tenant_isolation(api_client) -> None:
    content = b"Unique incident identifier: INC-92817 deployment rollback."
    headers = {"X-Organization-Id": "team-a"}
    first = api_client.post(
        "/api/v1/knowledge/documents",
        files={"file": ("incident.log", content, "text/plain")},
        headers=headers,
    )
    second = api_client.post(
        "/api/v1/knowledge/documents",
        files={"file": ("renamed.log", content, "text/plain")},
        headers=headers,
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["document_id"] == second.json()["document_id"]

    found = api_client.get(
        "/api/v1/knowledge/search",
        params={"q": "INC-92817 deployment rollback"},
        headers=headers,
    )
    hidden = api_client.get(
        "/api/v1/knowledge/search",
        params={"q": "INC-92817 deployment rollback"},
        headers={"X-Organization-Id": "team-b"},
    )
    assert found.status_code == hidden.status_code == 200
    assert found.json()["evidence"]
    assert hidden.json()["evidence"] == []


def test_document_versions_increment_when_source_content_changes(api_client) -> None:
    first = api_client.post(
        "/api/v1/knowledge/documents",
        files={"file": ("runbook.md", b"first revision", "text/markdown")},
    )
    second = api_client.post(
        "/api/v1/knowledge/documents",
        files={"file": ("runbook.md", b"second revision", "text/markdown")},
    )

    assert first.json()["version"] == 1
    assert second.json()["version"] == 2


def test_sensitive_action_requires_human_decision(api_client) -> None:
    created = api_client.post(
        "/api/v1/investigations",
        json={"request": "Review the service error report and identify missing evidence."},
    )
    investigation_id = created.json()["id"]
    approval = api_client.post(
        f"/api/v1/investigations/{investigation_id}/approvals",
        json={
            "action": "Apply the proposed payment-service configuration change",
            "rationale": "A human must review operational changes before execution.",
        },
    )
    assert approval.status_code == 201
    approval_id = approval.json()["id"]

    pending = api_client.get("/api/v1/approvals")
    assert any(item["id"] == approval_id for item in pending.json())

    decision = api_client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "rejected", "note": "Wait for verified deployment evidence."},
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "rejected"

    duplicate = api_client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "approved"},
    )
    assert duplicate.status_code == 409


def test_upload_rejects_unsupported_and_oversized_content(api_client, monkeypatch) -> None:
    from app.config import settings

    unsupported = api_client.post(
        "/api/v1/knowledge/documents",
        files={"file": ("malware.exe", b"not allowed", "application/octet-stream")},
    )
    assert unsupported.status_code == 415

    monkeypatch.setattr(settings, "ENTERPRISEIQ_MAX_UPLOAD_BYTES", 3)
    oversized = api_client.post(
        "/api/v1/knowledge/documents",
        files={"file": ("large.txt", b"four", "text/plain")},
    )
    assert oversized.status_code == 413


def test_upload_rejects_malformed_office_package(api_client) -> None:
    response = api_client.post(
        "/api/v1/knowledge/documents",
        files={"file": ("malformed.docx", b"not a zip package", "application/docx")},
    )
    assert response.status_code == 422


def test_configured_query_limit_applies_to_api_routes(api_client, monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "ENTERPRISEIQ_MAX_QUERY_CHARS", 3)
    investigation = api_client.post(
        "/api/v1/investigations",
        json={"request": "too many"},
    )
    search = api_client.get("/api/v1/knowledge/search", params={"q": "four"})
    legacy = api_client.post("/query", json={"q": "four"})

    assert investigation.status_code == 413
    assert search.status_code == 413
    assert legacy.status_code == 413


def test_api_key_authentication_binds_requests_to_configured_organization(
    api_client, monkeypatch
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "ENTERPRISEIQ_API_KEY", "local-test-key")
    monkeypatch.setattr(settings, "ENTERPRISEIQ_ORGANIZATION_ID", "company-a")
    unauthenticated = api_client.get("/api/v1/investigations")
    authenticated = api_client.post(
        "/api/v1/investigations",
        headers={"X-API-Key": "local-test-key", "X-Organization-Id": "company-b"},
        json={"request": "Investigate the production API timeout symptoms."},
    )

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 202
    assert authenticated.json()["organization_id"] == "company-a"

    frontend = api_client.get("/")
    script = re.search(r'src="(/assets/[^"]+\.js)"', frontend.text)
    assert script is not None
    assert api_client.get(script.group(1)).status_code == 200


def test_analysis_surfaces_explicit_status_conflicts_with_both_sources() -> None:
    from datetime import datetime, timezone

    from app.investigations.graph import analysis_node

    now = datetime.now(timezone.utc).isoformat()
    result = analysis_node(
        {
            "evidence": [
                {
                    "evidence_id": "ev-complete",
                    "source_id": "change-calendar",
                    "document_id": "doc-a",
                    "chunk_id": "chunk-a",
                    "excerpt": "order-service release 18 was marked completed",
                    "metadata": {"source": "calendar.csv"},
                    "sparse_score": 1.0,
                    "dense_score": None,
                    "retrieval_score": 1.0,
                    "retrieved_at": now,
                },
                {
                    "evidence_id": "ev-failed",
                    "source_id": "deployment-console",
                    "document_id": "doc-b",
                    "chunk_id": "chunk-b",
                    "excerpt": "order-service release 18 was marked failed",
                    "metadata": {"source": "console.log"},
                    "sparse_score": 0.9,
                    "dense_score": None,
                    "retrieval_score": 0.9,
                    "retrieved_at": now,
                },
            ]
        }
    )

    assert len(result["conflicts"]) == 1
    assert {ref["evidence_id"] for ref in result["conflicts"][0]["evidence_refs"]} == {
        "ev-complete",
        "ev-failed",
    }
    contradicted = [
        finding
        for finding in result["findings"]
        if finding["classification"] == "contradicted"
    ]
    assert len(contradicted) == 1


def test_langgraph_checkpoint_survives_saver_reopen(api_client) -> None:
    from app.investigations.graph import build_investigation_graph
    from app.persistence.checkpoints import persistent_checkpointer

    assert api_client.get("/health").json()["status"] == "ok"
    config = {"configurable": {"thread_id": "checkpoint-test"}}
    initial = {
        "investigation_id": "checkpoint-test",
        "organization_id": "local",
        "request": "Investigate the synthetic deployment timeout evidence.",
        "evidence": [],
        "hypotheses": [],
        "findings": [],
        "unresolved_questions": [],
        "tool_executions": [],
        "warnings": [],
    }
    with persistent_checkpointer() as saver:
        result = build_investigation_graph(saver).invoke(initial, config=config)
    assert result["report"]["summary"].endswith("No root cause is confirmed.")

    with persistent_checkpointer() as saver:
        saved = build_investigation_graph(saver).get_state(config).values
    assert saved["report"] == result["report"]


def test_startup_replays_interrupted_investigation(api_client) -> None:
    from sqlalchemy import select

    from app.investigations.service import resume_interrupted_investigations
    from app.persistence.database import InvestigationRecord, get_session_factory

    created = api_client.post(
        "/api/v1/investigations",
        json={"request": "Review an interrupted synthetic service incident."},
    )
    investigation_id = created.json()["id"]
    factory = get_session_factory()
    with factory() as session:
        record = session.scalar(
            select(InvestigationRecord).where(InvestigationRecord.id == investigation_id)
        )
        assert record is not None
        record.status = "running"
        session.commit()

    resume_interrupted_investigations()
    recovered = api_client.get(f"/api/v1/investigations/{investigation_id}")
    assert recovered.json()["status"] == "completed"
    assert recovered.json()["report"] is not None


def test_synthetic_scenario_is_ingested_and_tools_are_run_scoped(api_client) -> None:
    catalog = api_client.get("/api/v1/lab/scenarios")
    assert catalog.status_code == 200
    assert {item["scenario_id"] for item in catalog.json()} == {
        f"INC-{number:03}"
        for number in range(1, 11)
    }
    assert all(item["synthetic"] for item in catalog.json())
    assert "ground_truth" not in catalog.text.casefold()

    published_payment = api_client.post("/api/v1/lab/scenarios/INC-001/publish")
    published_auth = api_client.post("/api/v1/lab/scenarios/INC-002/publish")
    assert published_payment.status_code == published_auth.status_code == 201
    assert published_payment.json()["document_count"] == 10
    republished_payment = api_client.post("/api/v1/lab/scenarios/INC-001/publish")
    assert republished_payment.json()["documents"] == published_payment.json()["documents"]

    scoped_search = api_client.get(
        "/api/v1/knowledge/search",
        params={
            "q": "payment API database connection timeout",
            "simulation_scenario_id": "INC-001",
        },
    )
    assert scoped_search.status_code == 200
    assert scoped_search.json()["evidence"]
    assert {
        item["metadata"]["scenario_id"]
        for item in scoped_search.json()["evidence"]
    } == {"INC-001"}

    investigation = api_client.post(
        "/api/v1/investigations",
        json={
            "request": (
                "Investigate payment API failures and correlate database "
                "connection timeouts with deployment evidence."
            ),
            "simulation_scenario_id": "INC-001",
        },
    )
    assert investigation.status_code == 202
    result = api_client.get(f"/api/v1/investigations/{investigation.json()['id']}")
    assert result.json()["status"] == "completed"
    assert result.json()["simulation_scenario_id"] == "INC-001"
    assert result.json()["evidence"]
    assert all(
        item["metadata"]["scenario_id"] == "INC-001"
        for item in result.json()["evidence"]
    )
    tool_results = result.json()["tool_executions"]
    assert len(tool_results) == 5
    assert all(item["status"] == "completed" and item["simulated"] for item in tool_results)
    assert all(item["output"]["synthetic"] for item in tool_results)


def test_demo_scenario_summary_exposes_severity_and_source_inspection(api_client) -> None:
    scenarios = api_client.get("/api/v1/lab/scenarios")
    assert scenarios.status_code == 200
    summary = next(
        item for item in scenarios.json() if item["scenario_id"] == "INC-007"
    )
    assert summary["severity"] in {"info", "warning", "error", "critical"}
    assert summary["affected_services"]

    manifest = api_client.get("/api/v1/lab/scenarios/INC-007/evidence")
    assert manifest.status_code == 200
    assert manifest.json()["available"] is True
    assert all(source["available"] for source in manifest.json()["sources"])

    source = next(
        item
        for item in manifest.json()["sources"]
        if item["artifact_id"] == "application-logs"
    )
    artifact = api_client.get(
        f"/api/v1/lab/scenarios/INC-007/artifacts/{source['artifact_id']}"
    )
    assert artifact.status_code == 200
    assert artifact.json()["synthetic"] is True
    assert "correlation_id=" in artifact.json()["content"]
    assert "ground_truth" not in artifact.json()["source"]

    unknown = api_client.get(
        "/api/v1/lab/scenarios/INC-007/artifacts/../../ground_truth"
    )
    assert unknown.status_code == 404


def test_investigation_idempotency_reuses_record_and_rejects_key_reuse(
    api_client,
) -> None:
    headers = {"Idempotency-Key": "demo-run-inc-001-abc123"}
    payload = {
        "request": "Investigate the synthetic payment API failure evidence.",
        "simulation_scenario_id": "INC-001",
    }
    first = api_client.post(
        "/api/v1/investigations", headers=headers, json=payload
    )
    repeated = api_client.post(
        "/api/v1/investigations", headers=headers, json=payload
    )
    assert first.status_code == repeated.status_code == 202
    assert repeated.json()["id"] == first.json()["id"]

    other_organization = api_client.post(
        "/api/v1/investigations",
        headers={**headers, "X-Organization-Id": "demo-team-b"},
        json=payload,
    )
    assert other_organization.status_code == 202
    assert other_organization.json()["id"] != first.json()["id"]

    conflicting = api_client.post(
        "/api/v1/investigations",
        headers=headers,
        json={
            "request": "Investigate a different incident with another request.",
            "simulation_scenario_id": "INC-001",
        },
    )
    assert conflicting.status_code == 409


def test_workflow_failure_reports_last_persisted_stage(api_client, monkeypatch) -> None:
    class FailingGraph:
        def stream(self, state, config, stream_mode):
            yield {
                "intake": {
                    "plan": {
                        "objective": state["request"],
                        "tasks": [],
                        "max_steps": 8,
                    }
                }
            }
            raise RuntimeError("synthetic workflow failure")

    monkeypatch.setattr(
        "app.investigations.service.build_investigation_graph",
        lambda checkpointer: FailingGraph(),
    )
    created = api_client.post(
        "/api/v1/investigations",
        json={"request": "Investigate the synthetic payment timeout evidence."},
    )
    assert created.status_code == 202
    investigation_id = created.json()["id"]
    detail = api_client.get(f"/api/v1/investigations/{investigation_id}")
    assert detail.json()["status"] == "failed"

    events = api_client.get(
        f"/api/v1/investigations/{investigation_id}/events"
    ).json()
    failure = next(event for event in events if event["event_type"] == "failed")
    assert failure["data"]["failed_stage"] is None
    assert failure["data"]["last_completed_stage"] == "intake"
    assert "after intake completed; failing stage is unknown" in failure["message"]


def test_workflow_node_failure_identifies_failed_stage(api_client, monkeypatch) -> None:
    def fail_intake(state):
        raise RuntimeError("synthetic intake failure")

    monkeypatch.setattr("app.investigations.graph.intake_node", fail_intake)
    created = api_client.post(
        "/api/v1/investigations",
        json={"request": "Investigate the synthetic payment timeout evidence."},
    )
    investigation_id = created.json()["id"]
    events = api_client.get(
        f"/api/v1/investigations/{investigation_id}/events"
    ).json()
    failure = next(event for event in events if event["event_type"] == "failed")
    assert failure["data"]["failed_stage"] == "intake"
    assert "failed during intake" in failure["message"]


def test_lab_api_rejects_unknown_scenarios_and_does_not_expose_truth(api_client) -> None:
    unknown = api_client.get("/api/v1/lab/scenarios/INC-999/metrics")
    unpublished_truth = api_client.get("/api/v1/lab/scenarios/INC-001/ground_truth")
    invalid_investigation = api_client.post(
        "/api/v1/investigations",
        json={
            "request": "Investigate an unknown synthetic scenario safely.",
            "simulation_scenario_id": "INC-999",
        },
    )

    assert unknown.status_code == 404
    assert unpublished_truth.status_code == 404
    assert invalid_investigation.status_code == 404


def test_lab_log_and_metric_apis_return_synthetic_source_data(api_client) -> None:
    infra_logs = api_client.get(
        "/api/v1/lab/scenarios/INC-003/logs",
        params={"log_type": "infrastructure", "q": "queue backlog"},
    )
    metrics = api_client.get(
        "/api/v1/lab/scenarios/INC-003/metrics",
        params={"q": "queue depth"},
    )
    health = api_client.get("/api/v1/lab/scenarios/INC-003/health")
    deployments = api_client.get("/api/v1/lab/scenarios/INC-003/deployments")

    assert infra_logs.status_code == metrics.status_code == health.status_code == 200
    assert deployments.status_code == 200
    assert infra_logs.json()["synthetic"]
    assert infra_logs.json()["records"]
    assert metrics.json()["synthetic"]
    assert metrics.json()["records"]
    assert health.json()["synthetic"]
    assert health.json()["source"] == "generated event severity; not a live health probe"
    assert deployments.json()["records"]
    notification_health = next(
        service
        for service in health.json()["services"]
        if service["service_id"] == "notification-service"
    )
    assert notification_health["observed_status"] == "degraded_signal_observed"


def test_simulation_run_api_supports_progress_stop_replay_and_reset(api_client) -> None:
    reset = api_client.post("/api/v1/lab/reset")
    assert reset.status_code == 200
    started = api_client.post(
        "/api/v1/lab/runs",
        json={"scenario_id": "INC-008"},
    )
    assert started.status_code == 201
    run = started.json()
    assert run["synthetic"] is True
    assert run["status"] == "running"
    assert run["scenario_id"] == "INC-008"
    assert run["events"]

    listed = api_client.get("/api/v1/lab/runs")
    assert listed.status_code == 200
    assert any(item["run_id"] == run["run_id"] for item in listed.json())

    stopped = api_client.post(f"/api/v1/lab/runs/{run['run_id']}/stop")
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopped"

    replay = api_client.post(f"/api/v1/lab/runs/{run['run_id']}/replay")
    assert replay.status_code == 201
    assert replay.json()["replay_of"] == run["run_id"]
    assert replay.json()["seed"] == run["seed"]
    assert [
        event["event_id"] for event in replay.json()["events"]
    ] == [event["event_id"] for event in run["events"]]

    removed = api_client.post(f"/api/v1/lab/runs/{run['run_id']}/reset")
    assert removed.status_code == 200
    assert removed.json()["reset"] is True
    assert api_client.get(f"/api/v1/lab/runs/{run['run_id']}").status_code == 404

    cleared = api_client.post("/api/v1/lab/reset")
    assert cleared.status_code == 200
    assert cleared.json()["reset"] is True
    assert api_client.get("/api/v1/lab/runs").json() == []

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

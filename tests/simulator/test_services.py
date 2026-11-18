from app.simulator import (
    ENVIRONMENT_LABEL,
    ENVIRONMENT_NAME,
    SERVICE_CATALOG,
    ServiceKind,
)


def test_nexora_catalog_defines_the_required_synthetic_services() -> None:
    assert ENVIRONMENT_NAME == "Nexora Systems"
    assert "SYNTHETIC" in ENVIRONMENT_LABEL
    assert {service.name for service in SERVICE_CATALOG.values()} == {
        "API Gateway",
        "Payment Service",
        "Authentication Service",
        "Notification Service",
        "PostgreSQL",
        "Redis",
        "Message Queue",
        "Monitoring Service",
    }
    assert all(service.synthetic for service in SERVICE_CATALOG.values())


def test_service_topology_references_only_declared_internal_services() -> None:
    service_ids = set(SERVICE_CATALOG)

    for service in SERVICE_CATALOG.values():
        assert set(service.dependencies) <= service_ids
        assert set(service.monitors) <= service_ids

    assert SERVICE_CATALOG["postgresql"].kind == ServiceKind.DATABASE
    assert SERVICE_CATALOG["redis"].kind == ServiceKind.CACHE
    assert SERVICE_CATALOG["message-queue"].kind == ServiceKind.MESSAGE_BROKER
    assert SERVICE_CATALOG["monitoring-service"].monitors == tuple(
        service_id for service_id in SERVICE_CATALOG if service_id != "monitoring-service"
    )
    assert SERVICE_CATALOG["payment-service"].external_dependencies == (
        "Payment Gateway (simulated)",
    )

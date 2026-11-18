from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


ENVIRONMENT_NAME = "Nexora Systems"
ENVIRONMENT_LABEL = "SYNTHETIC ENVIRONMENT"


class ServiceKind(StrEnum):
    APPLICATION = "application"
    DATABASE = "database"
    CACHE = "cache"
    MESSAGE_BROKER = "message_broker"
    MONITORING = "monitoring"


@dataclass(frozen=True, slots=True)
class ServiceDefinition:
    service_id: str
    name: str
    kind: ServiceKind
    description: str
    dependencies: tuple[str, ...] = ()
    external_dependencies: tuple[str, ...] = ()
    monitors: tuple[str, ...] = ()
    synthetic: bool = True


_SERVICES = (
    ServiceDefinition(
        service_id="api-gateway",
        name="API Gateway",
        kind=ServiceKind.APPLICATION,
        description="Simulated public entry point that routes requests to Nexora services.",
        dependencies=(
            "authentication-service",
            "payment-service",
            "notification-service",
        ),
    ),
    ServiceDefinition(
        service_id="payment-service",
        name="Payment Service",
        kind=ServiceKind.APPLICATION,
        description="Simulated payment API and transaction orchestration service.",
        dependencies=("postgresql", "redis", "message-queue"),
        external_dependencies=("Payment Gateway (simulated)",),
    ),
    ServiceDefinition(
        service_id="authentication-service",
        name="Authentication Service",
        kind=ServiceKind.APPLICATION,
        description="Simulated identity, token issuance, and signing-key service.",
        dependencies=("postgresql", "redis"),
    ),
    ServiceDefinition(
        service_id="notification-service",
        name="Notification Service",
        kind=ServiceKind.APPLICATION,
        description="Simulated asynchronous email and webhook delivery service.",
        dependencies=("message-queue", "redis"),
    ),
    ServiceDefinition(
        service_id="postgresql",
        name="PostgreSQL",
        kind=ServiceKind.DATABASE,
        description="Simulated relational database for application records.",
    ),
    ServiceDefinition(
        service_id="redis",
        name="Redis",
        kind=ServiceKind.CACHE,
        description="Simulated cache and short-lived coordination store.",
    ),
    ServiceDefinition(
        service_id="message-queue",
        name="Message Queue",
        kind=ServiceKind.MESSAGE_BROKER,
        description="Simulated durable queue for asynchronous service events.",
    ),
    ServiceDefinition(
        service_id="monitoring-service",
        name="Monitoring Service",
        kind=ServiceKind.MONITORING,
        description="Synthetic metrics and health observations for the environment.",
        monitors=(
            "api-gateway",
            "payment-service",
            "authentication-service",
            "notification-service",
            "postgresql",
            "redis",
            "message-queue",
        ),
    ),
)

SERVICE_CATALOG: Mapping[str, ServiceDefinition] = MappingProxyType(
    {service.service_id: service for service in _SERVICES}
)

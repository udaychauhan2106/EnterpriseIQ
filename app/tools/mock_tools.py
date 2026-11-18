from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    status: str
    output: dict[str, Any]
    simulated: bool = True
    started_at: datetime
    completed_at: datetime


_READ_ONLY_TOOLS = (
    "search_incident_history",
    "query_structured_records",
    "get_deployment_history",
    "search_application_logs",
    "check_service_health",
)


def run_read_only_tools(query: str) -> list[dict[str, Any]]:
    """Return explicit non-live tool results; no real service is contacted."""
    del query
    results: list[dict[str, Any]] = []
    for tool_name in _READ_ONLY_TOOLS:
        now = datetime.now(timezone.utc)
        result = ToolResult(
            tool_name=tool_name,
            status="not_configured",
            output={
                "records": [],
                "message": "No mock fixture is configured; no live system was queried.",
            },
            started_at=now,
            completed_at=now,
        )
        results.append(
            {
                "id": str(uuid4()),
                **result.model_dump(mode="json"),
                "input": {},
            }
        )
    return results


def compare_timestamps(first: datetime, second: datetime) -> dict[str, float | str]:
    delta_seconds = (second - first).total_seconds()
    return {
        "relation": "after" if delta_seconds > 0 else "before" if delta_seconds < 0 else "same_time",
        "difference_seconds": abs(delta_seconds),
    }

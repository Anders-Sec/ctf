"""Response models for the staff health page (spec 057)."""

from pydantic import BaseModel


class CheckResponse(BaseModel):
    name: str
    #: ok | degraded | down | not_configured. "Not configured" is a valid state,
    #: not a fault — a red light for a deliberate setting teaches an admin to
    #: ignore red lights.
    state: str
    duration_ms: int | None
    detail: str | None


class ConnectionsResponse(BaseModel):
    #: In-process subscribers. Per-pod, like every other number here.
    scoreboard: int


class BuildResponse(BaseModel):
    version: str
    environment: str


class LoadResponse(BaseModel):
    window_minutes: int
    requests_per_minute: float
    p95_ms: float
    errors: int
    #: Resets on restart — which is itself informative, and is why it sits
    #: beside the figures it explains.
    uptime_seconds: int


class HealthReportResponse(BaseModel):
    checked_at: str
    checks: list[CheckResponse]
    connections: ConnectionsResponse
    build: BuildResponse
    load: LoadResponse

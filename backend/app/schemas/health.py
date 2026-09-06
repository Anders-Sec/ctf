"""Response models for the health and version endpoints."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    postgres: Literal["ok", "error"]
    redis: Literal["ok", "error"]


class VersionResponse(BaseModel):
    version: str
    environment: str

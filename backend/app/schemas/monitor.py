"""系统监控 Schema。"""

from typing import Optional

from pydantic import BaseModel, Field


class HealthCheckItem(BaseModel):
    status: str = Field(description="healthy / unhealthy")
    latency_ms: Optional[float] = None


class HealthResponse(BaseModel):
    status: str = Field(description="healthy / degraded / unhealthy")
    version: str
    uptime_seconds: int
    checks: dict[str, HealthCheckItem] = Field(default_factory=dict)

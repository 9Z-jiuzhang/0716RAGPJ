"""系统监控 Schema。"""

from typing import Optional

from pydantic import BaseModel, Field


class HealthCheckItem(BaseModel):
    status: str = Field(description="healthy / unhealthy / degraded")
    latency_ms: Optional[float] = None


class HealthResponse(BaseModel):
    status: str = Field(description="healthy / degraded / unhealthy")
    version: str
    uptime_seconds: int
    checks: dict[str, HealthCheckItem] = Field(default_factory=dict)


class SystemStatsResponse(BaseModel):
    user_count: int = 0
    kb_count: int = 0
    doc_count: int = 0
    active_sessions: int = 0
    task_queue_size: int = 0

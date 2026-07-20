"""系统监控 Schema。"""

from pydantic import BaseModel, Field


class HealthCheckItem(BaseModel):
    status: str = Field(description="healthy / unhealthy / degraded")
    latency_ms: float | None = None


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
    qa_trend_7d: list[int] = Field(default_factory=lambda: [0] * 7, description="近7天每日问答量")
    hit_rate_trend_7d: list[float] = Field(default_factory=lambda: [0.0] * 7, description="近7天每日命中率 0-1")
    guard_blocked_24h: int = Field(default=0, description="最近 24 小时被 Guard 阻拦次数")
    guard_blocked_7d: int = Field(default=0, description="最近 7 天被 Guard 阻拦次数")
    guard_recent_events: list[dict[str, object]] = Field(
        default_factory=list,
        description="最近阻拦事件的意图、原因码和时间，不包含用户完整问题",
    )

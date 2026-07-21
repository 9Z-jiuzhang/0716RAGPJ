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
    qa_trend_30d: list[int] = Field(default_factory=lambda: [0] * 30, description="近30天每日问答量")
    hit_rate_trend_30d: list[float] = Field(default_factory=lambda: [0.0] * 30, description="近30天每日命中率 0-1")
    error_24h: list[int] = Field(
        default_factory=lambda: [0] * 4,
        description="近24小时错误量（4 个等宽时段，旧→新）",
    )
    error_hourly_48h: list[int] = Field(
        default_factory=lambda: [0] * 48,
        description="近48小时每小时错误量（文档失败+向量化失败，旧→新）",
    )
    guard_blocked_24h: int = Field(default=0, description="最近 24 小时被 Guard 阻拦次数")
    guard_blocked_7d: int = Field(default=0, description="最近 7 天被 Guard 阻拦次数")
    guard_recent_events: list[dict[str, object]] = Field(
        default_factory=list,
        description="最近阻拦事件摘要（兼容首页）；完整列表见 /monitor/guard-events",
    )


class GuardBlockedEventItem(BaseModel):
    id: str
    created_at: str
    intent: str
    reason_code: str
    detector: str
    confidence: float
    actor_label: str = Field(description="攻击账号：注册用户名或「访客」")
    client_ip: str | None = None
    user_id: str | None = Field(default=None, description="注册用户 ID；访客为空")
    is_registered: bool = Field(description="是否为已注册用户")
    question_preview: str | None = Field(default=None, description="脱敏短摘要")


class GuardBlockedEventListResponse(BaseModel):
    items: list[GuardBlockedEventItem] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    blocked_24h: int = 0
    blocked_7d: int = 0

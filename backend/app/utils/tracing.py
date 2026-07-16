"""请求追踪与性能计时工具：贯穿问答全流程的可观测标识。"""
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generator


def new_request_id() -> str:
    """生成全局唯一的请求追踪 ID，对齐 API 契约中的 request_id 字段。"""
    return str(uuid.uuid4())


@dataclass
class PerformanceTracker:
    """
    单次问答请求的性能计时器。

    各阶段耗时以毫秒为单位记录，最终在 SSE done 事件中返回给前端。
    """

    request_id: str = field(default_factory=new_request_id)
    started_at: float = field(default_factory=time.perf_counter)
    stages_ms: dict[str, float] = field(default_factory=dict)

    @contextmanager
    def track(self, stage: str) -> Generator[None, None, None]:
        """上下文管理器：自动记录某业务阶段的耗时（毫秒）。"""
        start = time.perf_counter()
        try:
            yield
        finally:
            self.stages_ms[stage] = round((time.perf_counter() - start) * 1000, 2)

    @property
    def total_ms(self) -> float:
        """从请求开始到当前时刻的总耗时（毫秒）。"""
        return round((time.perf_counter() - self.started_at) * 1000, 2)

    def to_dict(self) -> dict:
        """序列化为 API 响应中的 performance 字段结构。"""
        return {
            "request_id": self.request_id,
            "total_ms": self.total_ms,
            "stages_ms": self.stages_ms,
        }

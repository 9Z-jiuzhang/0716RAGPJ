"""应用日志配置：stdout + 滚动文件，支持 request_id。"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import settings

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    """将 ContextVar 中的 request_id 注入到 LogRecord。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get() or "-"
        return True


class StructuredFormatter(logging.Formatter):
    """统一字段：timestamp / level / logger / message / request_id。"""

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return super().format(record)


def setup_logging() -> None:
    """配置根 logger：stdout + 滚动文件。"""
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    log_dir = Path(settings.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = StructuredFormatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | request_id=%(request_id)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    req_filter = RequestIdFilter()

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(fmt)
    stdout.addFilter(req_filter)
    root.addHandler(stdout)

    file_handler = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=settings.LOG_MAX_BYTES,
        backupCount=settings.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    file_handler.addFilter(req_filter)
    root.addHandler(file_handler)

    # 降低第三方噪音
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    logging.getLogger(__name__).info("logging initialized level=%s dir=%s", settings.LOG_LEVEL, log_dir)

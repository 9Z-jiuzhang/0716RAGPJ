"""安全校验占位。【对齐手册病毒/格式校验；病毒扫描 P1 占位】"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def virus_scan_placeholder(filename: str, content: bytes) -> None:
    """
    病毒扫描占位：当前仅记录日志，不拦截。
    【P1 暂不支持真实杀毒引擎，后续可接 ClamAV】
    """
    logger.info("virus_scan_placeholder ok file=%s size=%s", filename, len(content))


def validate_encoding_safe(content: bytes) -> None:
    """基础编码探测：空文件拒绝。"""
    if content is None or len(content) == 0:
        raise ValueError("空文件不可上传")

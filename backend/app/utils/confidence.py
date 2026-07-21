"""问答置信度归一化与等级映射。"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any, Literal

ConfidenceLevel = Literal["high", "medium", "low"]
INVALID_SCORE = -1.0


def normalize_score(value: Any, *, default: float = INVALID_SCORE) -> float:
    """将任意检索/模型分数规范到 [0,1]；非法值返回 -1。"""
    try:
        if value is None:
            return default
        num = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(num):
        return default
    if num < 0.0:
        return default
    # 已经是概率/相似度
    if num <= 1.0:
        return num
    # 1~1.5：多为浮点上溢或未截断的近满分，禁止当成「百分制」除以 100
    # （否则 1.05 会变成 1.05%，界面上全是「1 点几」）
    if num <= 1.5:
        return 1.0
    # 明确的百分制分数（如 85、72.5）
    if num <= 100.0:
        return num / 100.0
    return default


def clamp_display_score(value: Any) -> float:
    """引用展示用：非法时返回 -1，合法则夹到 [0,1]。"""
    return normalize_score(value, default=INVALID_SCORE)


def level_from_score(score: float) -> ConfidenceLevel:
    if score < 0:
        return "low"
    if score >= 0.75:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


def aggregate_retrieval_confidence(
    scores: Iterable[Any], *, no_evidence: bool = False
) -> tuple[ConfidenceLevel, float]:
    """基于检索命中分数汇总答案置信度。

    返回 (level, score)；score 为 0~1，无法计算时为 -1。
    """
    if no_evidence:
        return "low", INVALID_SCORE
    values = [normalize_score(s) for s in scores]
    values = [v for v in values if v >= 0]
    if not values:
        return "low", INVALID_SCORE
    # 取 Top-3 均值，避免长尾低分拖垮
    top = sorted(values, reverse=True)[:3]
    avg = sum(top) / len(top)
    return level_from_score(avg), round(avg, 4)

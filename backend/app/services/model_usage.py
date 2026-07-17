"""从 Langfuse Cloud 拉取模型用量指标，供模型管理页展示。

使用 Langfuse 公共 API 的每日指标接口（/api/public/metrics/daily），
按模型聚合 token / 调用次数 / 成本，并返回每日时间序列。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Langfuse Cloud 每日指标接口限流较严（免费档 10 次/日），
# 因此对原始返回做进程内 TTL 缓存，避免前端每次切换模型/刷新都打到上游。
_CACHE_TTL_SECONDS = 600  # 正常缓存 10 分钟
_CACHE: dict[int, dict[str, Any]] = {}  # days -> {"at": ts, "raw": [...], "fetched": iso}


class ModelUsageError(Exception):
    """Langfuse 用量查询失败。"""


def _enabled() -> bool:
    return bool(settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY)


async def _fetch_raw_daily(days: int) -> tuple[list[dict[str, Any]], Optional[str]]:
    """拉取（或复用缓存）Langfuse 原始每日指标。

    返回 (raw_days_data, notice)。命中新鲜缓存直接返回；
    上游限流/网络异常时回退到旧缓存（附提示），无缓存时抛出 ModelUsageError。
    """
    now = time.time()
    cached = _CACHE.get(days)
    if cached and (now - cached["at"]) < _CACHE_TTL_SECONDS:
        return cached["raw"], None

    now_dt = datetime.now(timezone.utc)
    start = now_dt - timedelta(days=days)
    params: dict[str, Any] = {
        "fromTimestamp": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "toTimestamp": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    url = settings.LANGFUSE_HOST.rstrip("/") + "/api/public/metrics/daily"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url,
                params=params,
                auth=(settings.LANGFUSE_PUBLIC_KEY, settings.LANGFUSE_SECRET_KEY),
            )
    except httpx.HTTPError as exc:
        if cached:
            return cached["raw"], f"Langfuse 暂时不可达，展示缓存数据（{exc}）"
        raise ModelUsageError(f"无法连接 Langfuse: {exc}") from exc

    if resp.status_code == 429:
        # 命中限流：回退旧缓存并给出可读提示
        retry_after = None
        try:
            retry_after = (resp.json().get("details") or {}).get("retryAfterSeconds")
        except Exception:
            pass
        hint = (
            f"Langfuse 用量接口已达调用上限，约 {int(retry_after) // 3600} 小时后恢复"
            if retry_after
            else "Langfuse 用量接口已达调用上限，请稍后再试"
        )
        if cached:
            return cached["raw"], f"{hint}（当前展示上次缓存数据）"
        raise ModelUsageError(hint)

    if resp.status_code >= 400:
        if cached:
            return cached["raw"], f"Langfuse 返回 HTTP {resp.status_code}，展示缓存数据"
        raise ModelUsageError(
            f"Langfuse 用量查询失败 HTTP {resp.status_code}: {resp.text[:300]}"
        )

    raw = resp.json().get("data") or []
    _CACHE[days] = {"at": now, "raw": raw, "fetched": now_dt.isoformat()}
    return raw, None


async def fetch_daily_metrics(
    *,
    days: int = 30,
    model: Optional[str] = None,
) -> dict[str, Any]:
    """拉取近 N 天的模型用量，按模型聚合。

    返回结构::

        {
          "enabled": bool,
          "host": str,
          "range": {"from": iso, "to": iso, "days": int},
          "totals": {...},              # 全部模型汇总
          "models": [                   # 每个模型一条
            {
              "model": str,
              "total_traces": int,
              "total_observations": int,
              "input_tokens": int,
              "output_tokens": int,
              "total_tokens": int,
              "total_cost": float,
              "daily": [{"date","observations","input_tokens",
                         "output_tokens","total_tokens","cost"}]
            }
          ]
        }
    """
    days = max(1, min(days, 180))
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    result: dict[str, Any] = {
        "enabled": _enabled(),
        "host": settings.LANGFUSE_HOST,
        "range": {
            "from": start.isoformat(),
            "to": now.isoformat(),
            "days": days,
        },
        "totals": {
            "total_traces": 0,
            "total_observations": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
        },
        "models": [],
        "notice": None,
    }

    if not _enabled():
        return result

    # 取（或复用缓存的）原始每日指标；限流/异常且无缓存时以提示返回（不硬失败）
    try:
        days_data, notice = await _fetch_raw_daily(days)
    except ModelUsageError as exc:
        result["notice"] = str(exc)
        return result
    result["notice"] = notice

    # model -> {aggregate, daily: {date -> row}}
    models: dict[str, dict[str, Any]] = {}

    for day in days_data:
        date = day.get("date")
        for usage in day.get("usage") or []:
            name = usage.get("model") or "unknown"
            if model and name != model:
                continue
            bucket = models.setdefault(
                name,
                {
                    "model": name,
                    "total_traces": 0,
                    "total_observations": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "total_cost": 0.0,
                    "_daily": {},
                },
            )
            in_tok = int(usage.get("inputUsage") or 0)
            out_tok = int(usage.get("outputUsage") or 0)
            tot_tok = int(usage.get("totalUsage") or (in_tok + out_tok))
            obs = int(usage.get("countObservations") or 0)
            trc = int(usage.get("countTraces") or 0)
            cost = float(usage.get("totalCost") or 0.0)

            bucket["input_tokens"] += in_tok
            bucket["output_tokens"] += out_tok
            bucket["total_tokens"] += tot_tok
            bucket["total_observations"] += obs
            bucket["total_traces"] += trc
            bucket["total_cost"] += cost

            bucket["_daily"][date] = {
                "date": date,
                "observations": obs,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "total_tokens": tot_tok,
                "cost": cost,
            }

    model_list: list[dict[str, Any]] = []
    totals = result["totals"]
    for bucket in models.values():
        daily = sorted(bucket.pop("_daily").values(), key=lambda x: x["date"] or "")
        bucket["daily"] = daily
        bucket["total_cost"] = round(bucket["total_cost"], 6)
        model_list.append(bucket)

        totals["total_traces"] += bucket["total_traces"]
        totals["total_observations"] += bucket["total_observations"]
        totals["input_tokens"] += bucket["input_tokens"]
        totals["output_tokens"] += bucket["output_tokens"]
        totals["total_tokens"] += bucket["total_tokens"]
        totals["total_cost"] += bucket["total_cost"]

    totals["total_cost"] = round(totals["total_cost"], 6)
    model_list.sort(key=lambda x: x["total_tokens"], reverse=True)
    result["models"] = model_list
    return result

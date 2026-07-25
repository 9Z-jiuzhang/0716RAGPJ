"""主题聚类骨架：从问答事件聚合关键词主题（隐私：默认仅聚合）。"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import QARequestEvent, QATopicCluster

logger = logging.getLogger(__name__)

_TOKEN = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}")


class TopicAnalyticsService:
    async def rebuild_from_events(self, db: AsyncSession, *, limit: int = 500) -> list[dict[str, Any]]:
        """基于问题预览关键词粗聚类；不落全文，仅存代表问句摘要。"""
        rows = (
            await db.scalars(
                select(QARequestEvent)
                .where(QARequestEvent.question_preview.is_not(None))
                .order_by(QARequestEvent.created_at.desc())
                .limit(limit)
            )
        ).all()
        counter: Counter[str] = Counter()
        samples: dict[str, str] = {}
        for row in rows:
            preview = row.question_preview or ""
            tokens = _TOKEN.findall(preview)
            for tok in tokens[:5]:
                counter[tok] += 1
                samples.setdefault(tok, preview)

        # 清理旧簇后写入 TopN
        existing = (await db.scalars(select(QATopicCluster))).all()
        for old in existing:
            await db.delete(old)

        created: list[dict[str, Any]] = []
        for name, count in counter.most_common(20):
            if count < 2:
                continue
            cluster = QATopicCluster(
                name=name,
                keywords=[name],
                representative_question=samples.get(name),
                sample_count=count,
                cluster_version="keyword-v1",
            )
            db.add(cluster)
            created.append({"name": name, "sample_count": count})
        await db.commit()
        return created


topic_analytics_service = TopicAnalyticsService()

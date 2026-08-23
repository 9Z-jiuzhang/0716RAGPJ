"""CJK 全文检索后端切换说明与可选 content_tsv 刷新。

`FULLTEXT_ANALYZER_BACKEND=zh_jieba` 仅改查询侧 CJK 插空格，不重建索引。
本脚本可选全量刷新 `document_chunks.content_tsv`（与查询插空格是两条独立路径）。
真 jieba / zhparser 分词见 2.1.14 / 2.2.x。

若需全量刷新 tsvector（例如从旧库迁移），可执行：

  python scripts/cjk_fulltext_migrate.py --dry-run
  python scripts/cjk_fulltext_migrate.py

需配置 POSTGRES_* 环境变量；生产执行前请备份。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from sqlalchemy import text

# 允许从项目根目录执行
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.core.database import SessionLocal  # noqa: E402


async def _run(dry_run: bool) -> None:
    stmt = text(
        """
        UPDATE document_chunks
        SET content_tsv = to_tsvector('simple', coalesce(content, ''))
        WHERE is_enabled = true
        """
    )
    async with SessionLocal() as session:
        if dry_run:
            count = await session.scalar(
                text("SELECT count(*) FROM document_chunks WHERE is_enabled = true")
            )
            print(f"[dry-run] 将刷新 {count} 条分段 content_tsv")
            return
        result = await session.execute(stmt)
        await session.commit()
        print(f"已刷新 content_tsv，影响行数：{result.rowcount or 0}")


def main() -> None:
    parser = argparse.ArgumentParser(description="刷新 document_chunks.content_tsv")
    parser.add_argument("--dry-run", action="store_true", help="仅统计，不写入")
    args = parser.parse_args()
    asyncio.run(_run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()

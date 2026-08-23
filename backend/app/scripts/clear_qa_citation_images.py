"""PR-A 上线后：清空 qa_messages.citations[].images 脏数据（整本 PDF 快照）。"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.qa import QAMessage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("clear_qa_citation_images")


def _strip_citation_images(citations: list | None) -> tuple[list | None, bool]:
    if not citations:
        return citations, False
    changed = False
    cleaned: list = []
    for item in citations:
        if isinstance(item, dict) and item.get("images"):
            new_item = dict(item)
            new_item["images"] = []
            cleaned.append(new_item)
            changed = True
        else:
            cleaned.append(item)
    return cleaned, changed


async def run(*, dry_run: bool = False, limit: int | None = None) -> int:
    updated = 0
    async with SessionLocal() as db:
        q = select(QAMessage).where(QAMessage.citations.isnot(None))
        if limit:
            q = q.limit(limit)
        rows = list((await db.scalars(q)).all())
        for msg in rows:
            new_citations, changed = _strip_citation_images(msg.citations)
            if not changed:
                continue
            updated += 1
            if dry_run:
                logger.info("would clear images message_id=%s", msg.id)
                continue
            msg.citations = new_citations
        if not dry_run and updated:
            await db.commit()
    logger.info("done updated=%s dry_run=%s", updated, dry_run)
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Clear stale citation images in qa_messages")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    parser.add_argument("--limit", type=int, default=0, help="最多处理条数（0=不限）")
    args = parser.parse_args()
    limit = args.limit if args.limit > 0 else None
    asyncio.run(run(dry_run=args.dry_run, limit=limit))


if __name__ == "__main__":
    main()

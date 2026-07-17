#!/usr/bin/env python3
"""写入 5.6 问答测试知识库（公开库 + 分段，启用全文检索）。

用法（在仓库根目录 0716RAGPJ）：
  python scripts/seed_qa_test_kb.py

说明：
- 创建/更新公开知识库「QA测试知识库-人事与差旅」
- 将 testdata/qa_kb/*.md 切成 chunk 写入 document_chunks（自动维护 content_tsv）
- 设置 current_index_version，使检索范围可见
- 不依赖 Chroma；hybrid 中全文路即可命中测试问题
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 容器内：应用在 /app，可将脚本与 testdata 拷到 /app 下执行
if not (ROOT / "backend" / "app").exists() and Path("/app/app").exists():
    ROOT = Path(os.environ.get("QA_SEED_ROOT", "/app"))
_BACKEND = ROOT / "backend" if (ROOT / "backend").exists() else ROOT
sys.path.insert(0, str(_BACKEND))

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.document import Document, DocumentChunk
from app.models.identity import User
from app.models.knowledge_base import KnowledgeBase

KB_NAME = "QA测试知识库-人事与差旅"
INDEX_VERSION = "qa-test-v1"
DATA_DIR = Path(os.environ.get("QA_TESTDATA_DIR", str(ROOT / "testdata" / "qa_kb")))
CHUNK_SIZE = 400
CHUNK_OVERLAP = 40


def _chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    cleaned = text.replace("\r\n", "\n").strip()
    if not cleaned:
        return []
    chunks: list[str] = []
    start = 0
    n = len(cleaned)
    while start < n:
        end = min(n, start + size)
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


async def seed() -> None:
    md_files = sorted(DATA_DIR.glob("*.md"))
    md_files = [p for p in md_files if p.name.upper() != "TEST_CASES.MD"]
    if not md_files:
        raise SystemExit(f"未找到测试文档：{DATA_DIR}")

    async with AsyncSessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        if admin is None:
            raise SystemExit("未找到 admin 用户，请先启动系统并完成身份初始化")

        kb = await db.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.name == KB_NAME,
                KnowledgeBase.deleted_at.is_(None),
            )
        )
        if kb is None:
            kb = KnowledgeBase(
                id=uuid.uuid4(),
                name=KB_NAME,
                type="faq",
                tags=["qa-test", "hr", "finance"],
                description="5.6 智能问答联调测试库（公开）",
                visibility="public",
                embedding_model="text-embedding-v3",
                chunk_size=CHUNK_SIZE,
                chunk_overlap=CHUNK_OVERLAP,
                status="active",
                current_index_version=INDEX_VERSION,
                creator_id=admin.id,
            )
            db.add(kb)
            await db.flush()
            print(f"创建知识库: {kb.id}")
        else:
            kb.visibility = "public"
            kb.status = "active"
            kb.current_index_version = INDEX_VERSION
            kb.description = "5.6 智能问答联调测试库（公开）"
            print(f"更新知识库: {kb.id}")

        # 清理旧测试文档，保证可重复执行
        old_docs = list(
            (await db.scalars(select(Document).where(Document.kb_id == kb.id))).all()
        )
        for doc in old_docs:
            await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
            await db.delete(doc)
        await db.flush()

        total_chunks = 0
        for path in md_files:
            text = path.read_text(encoding="utf-8")
            pieces = _chunk_text(text)
            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            doc = Document(
                id=uuid.uuid4(),
                kb_id=kb.id,
                filename=path.name,
                file_type="md",
                file_size=len(text.encode("utf-8")),
                file_path=f"qa-test/{path.name}",
                chunk_count=len(pieces),
                status="ready",
                content_hash=content_hash,
                creator_id=admin.id,
                raw_text=text,
                normalized_text=text,
                index_version=INDEX_VERSION,
            )
            db.add(doc)
            await db.flush()

            for idx, piece in enumerate(pieces):
                db.add(
                    DocumentChunk(
                        id=uuid.uuid4(),
                        document_id=doc.id,
                        kb_id=kb.id,
                        chunk_index=idx,
                        content=piece,
                        char_count=len(piece),
                        chunk_metadata={"source": path.name, "test": True},
                        is_enabled=True,
                    )
                )
                total_chunks += 1
            print(f"  文档 {path.name}: {len(pieces)} chunks")

        await db.commit()
        print(f"完成：kb_id={kb.id} chunks={total_chunks} index={INDEX_VERSION}")
        print("可用提问示例：司龄满 10 年不满 20 年的员工年假多少天？")


if __name__ == "__main__":
    asyncio.run(seed())

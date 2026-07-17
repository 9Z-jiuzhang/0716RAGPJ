"""知识库管理测试数据生成脚本。"""

import asyncio
import uuid
from datetime import datetime, timezone

from app.core.database import SessionLocal, engine
from app.models import Role, User
from app.models.base import Base
from app.models.document import Document, DocumentChunk
from app.models.index_version import IndexVersion
from app.models.knowledge_base import KBPermission, KnowledgeBase
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def create_test_kb(db: AsyncSession, admin_user: User):
    """创建测试知识库和文档。"""

    kb_types = [
        ("technical_doc", "技术文档"),
        ("product_manual", "产品手册"),
        ("faq", "FAQ"),
        ("general", "通用知识"),
    ]

    kbs = []

    for kb_type, name in kb_types:
        kb = KnowledgeBase(
            id=uuid.uuid4(),
            name=f"测试{name}库",
            type=kb_type,
            tags=[f"{name}", "测试", "demo"],
            description=f"这是一个{name}类型的测试知识库，用于验证知识库管理功能",
            visibility="public" if kb_type == "faq" else "restricted",
            embedding_model="text-embedding-v3",
            chunk_size=500,
            chunk_overlap=50,
            status="active",
            creator_id=admin_user.id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(kb)
        kbs.append(kb)

    await db.flush()

    for kb in kbs:
        iv = IndexVersion(
            kb_id=kb.id,
            version=f"v{datetime.now(timezone.utc).strftime('%Y%m%d')}-test001",
            is_current=True,
            chunk_count=0,
            status="active",
            config_snapshot={
                "embedding_model": kb.embedding_model,
                "chunk_size": kb.chunk_size,
                "chunk_overlap": kb.chunk_overlap,
            },
        )
        db.add(iv)
        kb.current_index_version = iv.version

        for i in range(3):
            doc_id = uuid.uuid4()
            doc = Document(
                id=doc_id,
                kb_id=kb.id,
                filename=f"测试文档{i+1}.md",
                file_type="markdown",
                file_size=1024,
                file_path=f"s3://test/{kb.name}/doc{i+1}.md",
                status="ready",
                creator_id=admin_user.id,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                chunk_count=3,
                raw_text=f"这是{kb.name}的第{i+1}个测试文档内容。",
                normalized_text=f"这是{kb.name}的第{i+1}个测试文档内容。",
            )
            db.add(doc)

            for j in range(3):
                chunk = DocumentChunk(
                    document_id=doc_id,
                    kb_id=kb.id,
                    chunk_index=j,
                    content=f"这是{kb.name}文档{i+1}的第{j+1}个分段内容。",
                    char_count=50,
                    is_enabled=True,
                )
                db.add(chunk)

    await db.commit()
    print(f"已创建 {len(kbs)} 个测试知识库，每个库包含 3 个测试文档")
    return kbs


async def setup_permissions(db: AsyncSession, admin_user: User):
    """设置测试权限。"""
    roles = list((await db.scalars(select(Role))).all())
    if not roles:
        print("未找到角色，跳过权限设置")
        return

    admin_role = roles[0]
    kbs = list((await db.scalars(select(KnowledgeBase))).all())

    for kb in kbs:
        db.add(
            KBPermission(
                kb_id=kb.id,
                role_id=admin_role.id,
                permission_code="kb:read",
            )
        )
        db.add(
            KBPermission(
                kb_id=kb.id,
                role_id=admin_role.id,
                permission_code="kb:write",
            )
        )
        db.add(
            KBPermission(
                kb_id=kb.id,
                role_id=admin_role.id,
                permission_code="kb:vectorize",
            )
        )

    await db.commit()
    print(f"已为 {len(kbs)} 个知识库设置权限")


async def main():
    """主入口。"""
    print("正在创建测试数据...")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        admin_user = await db.scalar(select(User).where(User.username == "admin"))
        if not admin_user:
            print("未找到 admin 用户，请先运行应用初始化")
            return

        await create_test_kb(db, admin_user)
        await setup_permissions(db, admin_user)

    print("测试数据创建完成！")


if __name__ == "__main__":
    asyncio.run(main())

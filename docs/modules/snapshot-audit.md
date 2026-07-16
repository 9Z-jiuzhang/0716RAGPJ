# 模块说明：快照、回退与审计（产品手册 5.8）

> 分支：`feature/sly-快照审计`  
> 对照：产品手册 V2.1 §5.8、`docs/API.md` §11–12、`contracts/openapi.json`

## 范围

本分支实现知识库快照、差异预览、选择性/整库回退、回退保护、审计日志查询，以及供其他写操作接入的自动快照钩子。

## 关键文件

| 路径 | 职责 |
|------|------|
| `backend/app/models/snapshot.py` / `audit_log.py` / `index_version.py` | ORM |
| `backend/app/schemas/snapshot.py` / `audit.py` | 请求响应契约 |
| `backend/app/repositories/snapshot.py` / `audit.py` | 数据访问与清理策略 |
| `backend/app/services/snapshot.py` / `audit.py` | 业务逻辑 |
| `backend/app/services/snapshot_hooks.py` | `take_auto_snapshot` 统一入口 |
| `backend/app/api/v1/snapshots.py` / `audit.py` | REST API |
| `frontend/admin/snapshots.html` / `audit.html` | 管理端页面 |

## 与其他模块协作

1. **文档 / 知识库写操作前**：调用 `take_auto_snapshot(..., SnapshotTrigger.AUTO_*)`
2. **向量化模块**：回退后索引为 `building`，重建完成后调用 `SnapshotService.activate_index_version`
3. **认证模块**：需提供 JWT 用户与 `snapshot:*` / `audit:read` 权限数据

## 本地验证

```bash
pip install -r requirements.txt
# 配置 .env 后
cd backend
uvicorn app.main:app --reload --port 8000
pytest ../backend/tests -q
```

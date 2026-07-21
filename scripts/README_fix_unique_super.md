# 唯一超管数据修复

## 背景

系统仅允许固定账号 `super` 作为超级管理员。历史数据中若其他用户误绑 `super_admin` 角色，需降级。

## 自动修复

应用启动时 `seed_identity_data()` 会：
1. 确保 `super` 账号存在并绑定 `super_admin`
2. 剥离其他账号上的 `super_admin`，默认降为 `admin`

## 手动脚本

在 API 容器内执行：

```bash
docker compose exec api python -c "import asyncio; from pathlib import Path; import sys; sys.path.insert(0,'/app'); ..."
```

或在仓库根目录（需配置好 DATABASE_URL / PYTHONPATH=backend）：

```bash
cd c:\Users\cao\Desktop\iqa\0716RAGPJ
$env:PYTHONPATH="backend"
python scripts/fix_unique_super_admin.py
```

脚本会打印被降级的用户名列表。

# AI 知识库 RAG 平台 — 贡献指南

> 版本与产品手册同步：V2.1

## 分支命名

| 类型 | 格式 | 示例 |
|------|------|------|
| 功能 | `feature/<模块>-<简述>` | `feature/auth-jwt` |
| 修复 | `fix/<简述>` | `fix/kb-permission-check` |
| 文档 | `docs/<简述>` | `docs/api-md-update` |
| 杂项 | `chore/<简述>` | `chore/ci-timeout` |

主分支：`main`（稳定）。日常开发建议基于 `develop`（若团队启用）或直接从 `main` 拉特性分支。

## 提交信息格式

采用 Conventional Commits：

```
<type>(<scope>): <简短中文或英文说明>

# type: feat | fix | docs | style | refactor | test | chore
# scope 可选: auth | kb | doc | qa | docker | contracts ...
```

示例：

```
feat(qa): 实现 SSE 流式问答接口
fix(kb): 修复知识库权限并集判断
docs(api): 补充命中率测试错误码说明
```

## Code Review

1. 所有合并需通过 Pull Request，至少 1 人 Approve
2. CI（ruff / black / pytest）必须通过
3. 涉及接口变更时，PR 需同步更新：
   - `contracts/openapi.json`
   - `docs/API.md`
4. 不在 PR 中提交 `.env`、密钥、本地数据卷

## 开发环境搭建

```bash
git clone https://github.com/9Z-jiuzhang/0716RAGPJ.git
cd 0716RAGPJ
cp .env.example .env
# 编辑 .env，填写全部 <请填写> 项

# 可选：本地 Python 虚拟环境（后端开发）
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 启动依赖与服务
docker compose up -d
```

## 运行测试

```bash
pytest backend/tests -v
```

## API 开发流程

1. 对照 `docs/API.md` / `contracts/openapi.json` 确认契约
2. 在 `backend/app/schemas/` 定义或对齐 Pydantic Schema
3. 在 `backend/app/api/v1/` 实现路由
4. 在 `backend/app/services/` 实现业务逻辑
5. 编写 `backend/tests/` 用例
6. 若契约有变：先改契约并评审，再改代码

## 前端开发流程

1. 以 OpenAPI 契约为唯一对接依据
2. 访客端页面放在 `frontend/guest/`，管理端在 `frontend/admin/`
3. 共享工具放在 `frontend/shared/`
4. 通过统一入口 `http://localhost:8080` 联调（Nginx 反向代理 `/api/`）

## 权限约定

- 权限标识格式：`资源:动作`（如 `kb:read`、`qa:ask`）
- 知识库级权限需同时校验功能权限 + 知识库授权范围
- 前端菜单隐藏不能替代后端鉴权

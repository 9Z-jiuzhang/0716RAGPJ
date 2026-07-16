# 前端模块开发说明（5.1）

> 对应产品手册：**5.1 前端模块**（含 **5.1.1 访客端**、**5.1.2 管理端**）  
> 设计规范：**4.3** 蓝白配色 `#1A73E8` / `#4A90D9` / `#0D47A1`；壳层为 **顶栏导航 + 全宽内容**（详见 UI 美化说明）  
> 分支建议：`feature/余飞鸿-前端`  
> 技术：原生 HTML + CSS + JavaScript（ES Module），无前端框架

---

## 1. 范围说明

本模块**只实现手册 5.1**，不包含后端业务实现。

| 端 | 覆盖内容 |
|----|----------|
| 访客端 `frontend/guest/` | 独立登录（内嵌注册）、按角色导航：访客仅问答 / 员工可上传 / 管理员进管理端；SSE 问答、历史、个人中心 |
| 管理端 `frontend/admin/` | 仪表盘、用户、角色、模型、知识库 CRUD/详情/文档/快照、命中率测试、审计、监控（Grafana 占位） |
| 共享 `frontend/shared/` | 设计令牌、布局组件、API/鉴权/路由/演示 Mock |

对接契约：`docs/API.md`、`contracts/openapi.json`。  
后端未就绪时自动进入**演示模式**（本地 Mock），保证页面可完整演示与联调 UI。

---

## 2. 目录结构

```text
frontend/
├── guest/                 # 访客端（Nginx 根路径 /）
│   ├── index.html
│   ├── css/guest.css
│   └── js/app.js
├── admin/                 # 管理端（/admin/）
│   ├── index.html
│   ├── css/admin.css
│   └── js/app.js
├── shared/                # 经 Nginx 映射为 /assets/
│   ├── css/               # variables / base / components / layout
│   └── js/                # api / auth / router / utils / mock
└── README.md              # 本文件
```

---

## 3. 开发流程（Windows）

### 3.1 拉代码并切到功能分支

```powershell
cd ~\0716RAGPJ
git fetch origin
git checkout feature/余飞鸿-前端
git pull
```

### 3.2 启动前端预览（二选一）

**方式 A：不依赖 Docker（推荐先用来验收页面）**

```powershell
cd ~\0716RAGPJ
python scripts\preview_frontend.py
```

浏览器打开：

| 入口 | 地址 |
|------|------|
| 访客端 | http://127.0.0.1:5500/ |
| 管理端 | http://127.0.0.1:5500/admin/ |

**方式 B：Docker（需 Docker Desktop 已运行，且 `.env` 已填写）**

```powershell
cd ~\0716RAGPJ
docker compose -f docker-compose.frontend.yml up -d
```

| 入口 | 地址 |
|------|------|
| 访客端 | http://localhost:8080/ |
| 管理端 | http://localhost:8080/admin/ |

### 3.4 改代码

1. 用 Cursor 打开 `C:\Users\Lenovo\0716RAGPJ`
2. 只改 `frontend/` 下文件（本任务范围）
3. **每一处逻辑保持中文注释**
4. 保存后刷新浏览器（静态资源已挂载，一般无需重建镜像）

### 3.5 自测清单（对照手册）

**访客端 5.1.1**

- [ ] 未登录（访客）顶栏仅「智能问答」+「登录」；不能上传
- [ ] 打开 `#/login` 为独立登录页；注册在登录页 Tab 内，无单独注册导航
- [ ] 演示 `super` 可见用户/角色写入；`admin` 用户列表只读、无角色写入
- [ ] `staff_a` / `staff_b` 上传目标库分别为 A/B 部门库
- [ ] 演示账号 `user`：问答 + 历史 + 个人中心，无上传
- [ ] 演示账号 `admin`/`super`：登录后进入 `/admin/`；右上有「智能对话」「退出」
- [ ] 发送问题有流式输出；有引用与置信提示；未命中不编造
- [ ] 故意问无法命中内容时，提示未找到依据 

**管理端 5.1.2**

- [ ] 需登录；右上角有「智能对话」「退出」  
- [ ] 仪表盘含：库/文档/用户数、7 天问答与命中率、资源与错误图、队列  
- [ ] 用户列表含账号、昵称、状态、角色、创建/登录时间与操作  
- [ ] 角色 / 模型 / 知识库 / 文档 / 快照 / 命中测试 / 审计 / 监控页可访问  
- [ ] 危险操作（禁用用户、删除、回退）有确认弹窗  

### 3.6 提交推送

```powershell
cd ~\0716RAGPJ
git status
git add frontend/ docker/nginx/nginx.conf
git commit -m "feat(frontend): 实现手册5.1访客端与管理端页面"
git push
```

---

## 4. 路由对照（手册）

### 访客端（Hash）

| 手册路由 | 实现 |
|----------|------|
| `/` | `#/` 问答 |
| `/login` | `#/login` 独立登录页（内嵌注册 Tab） |
| `/register` | `#/register` 同登录页，打开注册 Tab |
| `/history` | `#/history`（需登录） |
| `/profile` | `#/profile`（需登录） |
| （上传） | `#/upload`（员工 / 管理员或 `kb:upload`） |

### 角色与可见入口（演示，对齐手册 §3）

| 身份 | 演示账号（密码任意） | 权限要点 | 登录后 |
|------|----------------------|----------|--------|
| 访客 | 不登录 | 仅公开库问答 | 仅智能问答 |
| 注册用户 | `user` | `qa:ask` | 问答 + 历史 + 个人中心 |
| A部门员工 | `staff_a` | ≈ kb_admin，仅 A 部门库上传/维护 | 问答 + 上传（A 库）+ 历史（不进管理端） |
| B部门员工 | `staff_b` | ≈ kb_admin，仅 B 部门库 | 同上（B 库） |
| 普通管理员 | `admin` | 知识库/文档/测试/监控全量；**无** user/role 写入、**无** model 写入 | `/admin/`（菜单按权限） |
| 超级管理员 | `super` / `demo` | 手册系统管理员全量（含用户角色与模型配置） | `/admin/` 全菜单 |

### 管理端（Hash，页面挂在 `/admin/`）

| 手册路由 | 实现 |
|----------|------|
| `/admin` | `#/admin` |
| `/admin/users` | `#/admin/users` |
| `/admin/roles` | `#/admin/roles` |
| `/admin/models` | `#/admin/models` |
| `/admin/knowledge-bases` | `#/admin/knowledge-bases` |
| `/admin/knowledge-bases/:id` | `#/admin/knowledge-bases/:id` |
| `.../documents` | `#/admin/knowledge-bases/:id/documents` |
| `.../snapshots` | `#/admin/knowledge-bases/:id/snapshots` |
| `/admin/hit-test` | `#/admin/hit-test` |
| `/admin/audit` | `#/admin/audit` |
| `/admin/monitor` | `#/admin/monitor` |

使用 Hash 路由，兼容 Nginx `try_files` 与本地刷新。

---

## 5. 样式规范落地

| 手册要求 | 代码位置 |
|----------|----------|
| 主色 `#1A73E8` | `shared/css/variables.css` |
| 辅助色 `#4A90D9` `#0D47A1` | 同上 |
| 左侧导航 + 右侧内容（手册原文） | 已调整为 **顶栏 + 全宽**，见 `README-UI美化.md` |
| 圆角卡片、浅色背景 | `components.css` + `base.css` |
| 危险操作确认弹窗 | `shared/js/utils.js` → `confirmDialog` |
| 管理端「智能对话 / 退出」 | `admin/js/app.js` 顶栏 |

**UI 美化说明（布局 / 配色细化，不改需求）**：见 [`README-UI美化.md`](./README-UI美化.md)。

---

## 6. 与后端联调说明

1. API Base：`/api/v1`（经 8080 反代到后端）  
2. 认证头：`Authorization: Bearer <access_token>`  
3. 问答：`POST /qa/ask`，SSE 事件 `chunk` / `citations` / `done` / `error`  
4. 当接口 **501** 或网络失败：自动启用 `shared/js/mock.js` 演示数据  
5. 强制演示：浏览器控制台执行  
   `localStorage.setItem('rag_force_demo','1'); location.reload();`  
   关闭：`localStorage.removeItem('rag_force_demo');`

前端菜单按权限码隐藏，**不能替代后端鉴权**（手册 5.3）。

---

## 7. 常见问题

| 问题 | 处理 |
|------|------|
| 样式 404 `/assets/css/...` | 确认 `docker compose` 已启动 `web`，且 `nginx.conf` 含 `/assets/` |
| 管理端刷新 404 | 已用 `@admin_spa` 回退；请访问 `/admin/`（带尾斜杠） |
| 一直演示模式 | 后端未实现属正常；后端就绪后清除 `rag_force_demo` 并保证 API 非 501 |
| 直接双击 html 打开失败 | 必须通过 Nginx/8080 访问，ES Module 与绝对路径 `/assets` 依赖 HTTP |

---

## 8. 验收建议（给组长）

1. 对照本 README「自测清单」点验  
2. 对照手册 5.1.1 / 5.1.2 路由与功能点表  
3. 查看代码中文注释是否完整、交互是否含确认弹窗与引用展示  
4. 合并前走 PR，勿直接推 `main`

---

## 9. 变更文件一览

- 新增：`frontend/guest/**`、`frontend/admin/**`、`frontend/shared/**`、`frontend/README.md`
- 调整：`docker/nginx/nginx.conf`（管理端 SPA 回退与 `/admin` 跳转）
- UI 美化：`frontend/README-UI美化.md` + 各端 CSS（见该文档落地清单）

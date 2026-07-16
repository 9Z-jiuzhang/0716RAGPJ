# 组员协作开发完整流程（Windows）

> 仓库：[9Z-jiuzhang/0716RAGPJ](https://github.com/9Z-jiuzhang/0716RAGPJ)  
> 示例组员：**余飞鸿**（前端 · 手册 5.1）  
> 示例功能分支：`feature/余飞鸿-前端`  
> 环境：Windows + PowerShell + Git  
> 集成分支：**`develop`**（没有 `dev`）  
> 稳定主干：**`main`**

本文按「所有人开发新功能统一流程」写成可直接复制执行的步骤。

---

## 0. 分支约定（先看清再动手）

| 分支 | 用途 |
|------|------|
| `main` | 稳定主干（GitHub 默认分支） |
| `develop` | **日常集成分支**：大家 PR 都合到这里 |
| `feature/余飞鸿-前端` | 个人功能分支（格式：`feature/名字-功能`） |
| 其他 `feature/...` | 其他组员功能分支，互不直接改 |

**不要**直接往 `main` / `develop` 上 `push` 业务代码；只推自己的 `feature/...`，再开 PR。

---

## 1. 每天开工：切 develop，拉最新

```powershell
cd C:\Users\Lenovo\0716RAGPJ

git fetch origin
git checkout develop
git pull origin develop
```

### 核查

```powershell
git branch
git status
```

- 当前分支为 `develop`
- `git status` 为干净，或只有你自己未提交的改动（不要混进别人的未提交文件）

若提示没有本地 `develop`：

```powershell
git checkout -b develop origin/develop
git pull origin develop
```

---

## 2. 基于 develop 建 / 切自己的功能分支

### 2.1 第一次建分支（余飞鸿 · 前端）

```powershell
git checkout develop
git pull origin develop
git checkout -b feature/余飞鸿-前端
git push -u origin feature/余飞鸿-前端
```

### 2.2 分支已经建过（日常）

```powershell
git checkout feature/余飞鸿-前端
git merge develop
```

有冲突就解决 → `git add .` → `git commit -m "merge: 同步 develop"`。

### 核查

```powershell
git branch -vv
```

应看到 `* feature/余飞鸿-前端`，并跟踪 `origin/feature/余飞鸿-前端`。

---

## 3. 写代码 → 提交 → 推个人分支

### 3.1 开发

只改自己职责范围内的文件（余飞鸿：主要是 `frontend/` 及相关配置）。

### 3.2 提交前检查（务必）

```powershell
git status
```

确认 **没有** `.env`、密钥、本机缓存。本仓库 `.env` 已在 `.gitignore` 中。

推荐按范围添加（比盲目 `git add .` 更安全）：

```powershell
git add frontend/
git add docker/nginx/nginx.conf
git add docker-compose.frontend.yml
git add scripts/preview_frontend.py
```

若确认无敏感文件，也可用：

```powershell
git add .
```

### 3.3 提交

```powershell
git commit -m "feat(frontend): 实现手册5.1访客端与管理端及角色分流UI"
```

提交说明建议用 Conventional Commits，例如：

- `feat(frontend): ...`
- `fix(frontend): ...`
- `docs(frontend): ...`

### 3.4 推送个人分支

```powershell
git push -u origin feature/余飞鸿-前端
```

之后同一分支可直接：

```powershell
git push
```

### 核查

浏览器打开：

https://github.com/9Z-jiuzhang/0716RAGPJ/tree/feature/余飞鸿-前端

能看到你的最新提交和 `frontend/` 等文件即可。

---

## 4. 在 GitHub 开 PR（目标选 develop）

1. 打开 https://github.com/9Z-jiuzhang/0716RAGPJ  
2. 会出现 **Compare & pull request**，或点 **Pull requests → New pull request**  
3. 设置：
   - **base（目标）：`develop`**
   - **compare（来源）：`feature/余飞鸿-前端`**
4. 标题示例：`feat(frontend): 实现手册5.1访客端与管理端`  
5. 正文可写：

```markdown
## Summary
- 实现产品手册 5.1 访客端 / 管理端
- 顶栏布局与蓝白配色；角色分流（访客 / 员工A·B / 普通·超级管理员）
- 演示模式与前端预览脚本

## Test plan
- [ ] 演示账号：super / admin / staff_a / staff_b / user
- [ ] 退出回到登录页
- [ ] 8080 或 5500 预览页面正常
```

6. 创建 PR → 等组员 / 组长 **Review** → 通过后 **Merge into develop**

### 注意

- 目标分支选错成 `main` 时，先问组长是否允许；当前统一流程应以 **`develop`** 为准。  
- 合并后不要删别人的分支；自己的功能分支是否删除听组长安排。

---

## 5. 完整命令速查（余飞鸿当天一份）

```powershell
cd C:\Users\Lenovo\0716RAGPJ

# ① 同步集成分支
git fetch origin
git checkout develop
git pull origin develop

# ② 回到自己的功能分支并带上 develop 最新
git checkout feature/余飞鸿-前端
git merge develop

# ③ 改代码后提交推送
git add frontend/ docker/nginx/nginx.conf docker-compose.frontend.yml scripts/preview_frontend.py
git status
git commit -m "feat(frontend): 实现手册5.1访客端与管理端及角色分流UI"
git push origin feature/余飞鸿-前端

# ④ 浏览器：PR  base=develop  compare=feature/余飞鸿-前端
```

---

## 6. 其他组员怎么套用（改名字即可）

| 项目 | 余飞鸿（示例） | 你改成 |
|------|----------------|--------|
| 功能分支 | `feature/余飞鸿-前端` | `feature/张三-命中率测试` |
| 本地目录 | `C:\Users\Lenovo\0716RAGPJ` | 你的克隆路径 |
| 提交说明 | `feat(frontend): ...` | `feat(hit-test): ...` |
| PR 目标 | 始终 `develop` | 始终 `develop` |

示例（张三 · 命中率测试页）：

```powershell
git checkout develop
git pull origin develop
git checkout -b feature/zhangsan-hit-test-page
# ... 开发 ...
git add .
git commit -m "feat: 新增命中率测试页面下拉联动"
git push -u origin feature/zhangsan-hit-test-page
# GitHub PR → base: develop
```

---

## 7. 常见问题

| 情况 | 处理 |
|------|------|
| `dev` 不存在 | 仓库只有 **`develop`**，不要写 `dev` |
| `git pull` 有冲突 | 打开冲突文件改完 → `git add .` → `git commit` |
| push 被拒 | 先 `git pull origin feature/余飞鸿-前端`（或先 merge develop）再 push |
| 误提交 `.env` | `git restore --staged .env`，确认 ignore 后再 commit |
| 想先看别人合进 develop 的代码 | `git checkout develop` → `git pull` → 再 merge 进自己的 feature 分支 |

---

## 8. 相关文档

| 文档 | 说明 |
|------|------|
| [CONTRIBUTING.md](./CONTRIBUTING.md) | 分支命名、Commit 规范、Review 要求 |
| [frontend/README.md](./frontend/README.md) | 前端 5.1 开发与自测 |
| [frontend/README-UI美化.md](./frontend/README-UI美化.md) | 前端布局与角色分流说明 |

---

**一句话：**每天 `develop` 拉最新 → 在 `feature/余飞鸿-前端` 开发 → `commit` + `push` → GitHub PR 合进 **`develop`**。

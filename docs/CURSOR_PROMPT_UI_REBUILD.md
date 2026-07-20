# Cursor 提示词：企业知识库 · TechStart Pro UI（当前落地版）

> **用法**：新对话中 `@docs/CURSOR_PROMPT_UI_REBUILD.md`，并说「按此提示词继续打磨 / 验收 / 修某页」。  
> **分支**：优先在 `ui` 分支作业。  
> **参考**：[TechStart Pro](https://techstartpro.bs.designtocodes.com/#about)

---

## 角色与目标

你是精通 **Modern Dark SaaS / Glassmorphism / 微动效** 的前端工程师。  
本仓库前端是 **原生 ES Module SPA**（**非** Next.js / **非** MUI / **非** Tailwind 作为主栈）。

任务：用 **CSS 设计令牌 + 现有 class 覆盖 + 极少视觉层 JS**，保持并演进当前 **TechStart Pro 深色玻璃拟态** 体验。

**一句话**：换皮不换骨——功能、API、鉴权、SSE、路由、权限判断不变。

---

## 绝对红线

1. **零业务逻辑修改**：禁止改 API 调用、State、Router 匹配规则、数据库交互、SSE、鉴权判断。  
2. **全量视觉一致**：管理端与访客端所有主路由都要符合本规范，不要只改一页。  
3. **保留功能入口**：按钮 / 输入 / 链接改样式后，原有点击与跳转必须保留。  
4. **禁止技术栈迁移**：不要引入 React/Vue/MUI；不要把提示词里的 Tailwind 配置原样照搬，一律改写为 **CSS Variables + 现有 class**。

---

## 技术现实（写代码前先认清）

| 项 | 事实 |
|----|------|
| 结构 | `frontend/guest` 访客端 · `frontend/admin` 管理端 · `frontend/shared` 共享 |
| 静态映射 | Nginx：`/assets/*` → `shared/*` |
| 主题入口 | `variables.css` → `base.css` → `components.css` → `layout.css` → `motion.css` → 端内 css |
| 动效入口 | `shared/js/motion.js`（`initMotion` / `runCountUps`） |
| 缓存戳 | `frontend/*/index.html` 的 `?v=`（当前建议延续 `ui-20260721ts7` 或递增） |

JS 里**仅允许**为视觉服务的改动：HTML 字符串中的 class / 少量包裹标签、壳层挂 `.ambient-orbs`、`playPageEnter`、CountUp 属性、图表 `--bar-h` 等。

---

## 设计语言（必须遵守）

### 色彩

| 角色 | 值 | 场景 |
|------|-----|------|
| 主背景 | `#0B0F19` | 全局底层（禁止纯黑 `#000` 当主背景） |
| 玻璃面 | `rgba(255,255,255,0.05)` | 卡片 / 弹窗 / 悬浮面板 |
| 强调渐变 | `#6366f1 → #a855f7` | 主按钮、激活态、统计描边、渐变字 |
| 主文本 | `rgba(255,255,255,0.9)` | 标题、关键字段 |
| 正文 | `rgba(255,255,255,0.72)` | 表体、说明 |
| 次文本 | `rgba(255,255,255,0.5)` | 辅助、占位、表头 |
| 描边 | `rgba(255,255,255,0.08)` | 玻璃边 |

### 材质（Glass）

```css
background: rgba(255, 255, 255, 0.05);
backdrop-filter: blur(12px);
-webkit-backdrop-filter: blur(12px);
border: 1px solid rgba(255, 255, 255, 0.08);
box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
```

工具类：`.glass-panel`（与 `.card` 同材质）。

### 字体与圆角

- 字体：`Inter` → `Space Grotesk`（见 `--font-sans`）  
- 圆角：基础 **16px** · 卡片/弹窗 **24px** · 按钮胶囊 `--radius-pill`

### 缓动

- 默认：`cubic-bezier(0.4, 0, 0.2, 1)`  
- 微交互：~180ms · 页面过渡：~340ms  
- 小弹跳仅用于图标等小型元素：`cubic-bezier(0.34, 1.56, 0.64, 1)`  
- 必须尊重 `prefers-reduced-motion`

---

## 布局与组件约定（已落地，勿回退）

### 管理端壳层

- 侧栏：浮动玻璃岛；**active** = 渐变底 + 左侧光条 + 图标反馈  
- 顶栏：玻璃条；与侧栏同一暗色体系  
- 分组：工作台 / 组织与权限 / 知识资产 / 质量与运维  

### Dashboard

- **Bento** 非对称网格（如 `span-8` + `span-4`）  
- 统计卡：玻璃 + 霓虹描边；数值用 `[data-count-up]` + `runCountUps()`  
- 柱图：`--bar-h` + `chart-grow` 入场；hover 外发光  

### 表格页（用户 / 角色 / 部门 / 评估 / 会话等）

- 无纵向分割线；横线 `rgba(255,255,255,0.05)`  
- 表头：uppercase · 字重 700 · ~11–12px · `letter-spacing: 0.05em~0.06em` · 次文本色  
- 状态：辉光胶囊 Badge（约 10% 底色 + 同色描边/外光）  
- 操作列：`.table-actions` **单行 nowrap**；Outlined 小按钮；右对齐  
- 账号等主键：`.cell-primary`；时间：`.cell-time` 次文本  

### 列表高度（重要）

- **数据少时卡片随内容收起**，禁止大块空白撑满一屏  
- `.panel-fill` **默认不**设大 `min-height`，不 `flex-grow` 拉高  
- `#pageRoot` / `.page-grid`：`align-items: start`，子项 `height: auto`  
- 仅双栏必须等高时才加 `.panel-fill-stretch`  

### 聊天（访客）

- 消息区尽量无重边框，沉浸铺开  
- 用户气泡：主色渐变；AI 气泡：玻璃  
- 底部输入：悬浮玻璃；`:focus-within` 霓虹光晕  

### 登录页（一体舞台，禁止左右分割）

- 全页粒子 + 流动光晕覆盖视口  
- 居中舞台：品牌 → **大标题**（渐变强调词）→ 说明 → 横向能力胶囊 → **嵌入式**玻璃登录卡  
- 输入：暗色玻璃（`.auth-input`），禁止浅灰实心输入框  
- 主按钮：胶囊渐变 + 发光 Hover  

---

## 动效清单（已落地）

| 能力 | 位置 |
|------|------|
| 粒子网络背景 | `motion.js` → `#bgFxCanvas` · `pointer-events: none` |
| 光晕呼吸漂移 | `.ambient-orbs` + `.auth-materio-glow` |
| 按钮 Hover 上浮发光 | `.btn` + `motion.css` |
| Click 涟漪 | `.btn-ripple`（事件委托） |
| 卡片鼠标聚光 | `.fx-spot` + `--spot-x/y`（勿用伪元素覆盖侧栏霓虹条） |
| 页面进入 | `#pageRoot.page-enter` · `playPageEnter()` |
| 图表生长 / CountUp | Dashboard `renderBars` / `data-count-up` |
| 顶栏指示线 | `.topnav-links .nav-item::after` scaleX |

---

## 关键文件地图

| 文件 | 职责 |
|------|------|
| `frontend/shared/css/variables.css` | 令牌 |
| `frontend/shared/css/base.css` | body 光晕、滚动条 |
| `frontend/shared/css/components.css` | 按钮/卡片/表单/表格/Badge/空状态/`panel-fill` |
| `frontend/shared/css/layout.css` | 壳层、`#pageRoot` 高度策略 |
| `frontend/shared/css/motion.css` | 全局动效 |
| `frontend/shared/js/motion.js` | 粒子、涟漪、聚光、CountUp |
| `frontend/admin/css/admin.css` | 侧栏、Dashboard、知识库卡 |
| `frontend/guest/css/guest.css` | 登录一体页、聊天、上传/历史 |
| `frontend/admin/js/app.js` · `guest/js/app.js` | 仅视觉相关模板/壳层 |
| `frontend/*/index.html` | 字体 + CSS/JS `?v=` 缓存戳 |

**不要**再启用浅色 `flow-field.js` 作为主背景（已被暗色 `motion.js` 替代）。

---

## 继续打磨时的执行顺序

1. 先改 **令牌 / 共享 CSS**，再动端内 css，最后才动 JS 模板 class。  
2. 改完递增 `?v=`（admin + guest 同步），提醒硬刷新。  
3. 验收至少覆盖：登录、Dashboard、用户表、评估/会话列表、问答页、侧栏切换。  

---

## 验收清单

- [ ] 全局深空背景 + 粒子/光晕，非死黑、不挡点击  
- [ ] 玻璃卡片/侧栏/弹窗材质统一  
- [ ] Dashboard：Bento + CountUp + 柱生长  
- [ ] 表格：无纵线、辉光 Badge、操作列单行不折行堆叠  
- [ ] **少数据列表卡收起**，无大片空洞  
- [ ] 登录：一体居中舞台，无左右分割；输入暗色玻璃  
- [ ] 聊天：渐变/玻璃气泡 + 输入聚焦光晕  
- [ ] 按钮涟漪 / 卡片聚光 / 页面过渡正常  
- [ ] `prefers-reduced-motion` 下动效关闭或降级  
- [ ] 硬刷新后新 `?v=` 生效；控制台无业务回归  

---

## 禁止事项

- 改 API / auth / SSE / 路由业务逻辑  
- 把登录改回左右分栏  
- 给 `.panel-fill` 加回「默认占满一屏」的大 `min-height`  
- 浅色 Materio 白底卡片、实心浅灰输入框回流  
- 未要求时 push / merge 到 `develop`、提交密钥  

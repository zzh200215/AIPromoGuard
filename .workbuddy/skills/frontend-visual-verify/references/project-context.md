# 项目上下文（前端视觉验证专用）

> 供 `frontend-visual-verify` skill 使用。修改前端结构/tokens 后应回来同步此文件。

## 页面路由清单（20 个视图，`src/router/routes.ts`）

| 路由 | 视图 | 备注 |
|---|---|---|
| `/login` | LoginView | 独立设计（纸墨封面），不随主题切换 |
| `/` → `dashboard` | DashboardView | 驾驶舱：待办卡网格 + 欢迎标题 |
| `tasks` / `tasks/new` / `tasks/:id` | 任务列表 / 新建 / 详情（含 ReviewWorkbench 复核台） | 核心业务流 |
| `batches` / `batches/:id` | 批次列表 / 详情 | |
| `impact` / `materials` | 影响中心 / 材料台账 | |
| `knowledge/*` | regulations / rules / search / graph / trends | 知识库 5 页 |
| `admin/*` | users / monitor / feedback | 系统管理 3 页 |
| `/403` + 通配 | 异常页 | |

侧栏（`layouts/MainLayout.vue`）分组：工作台 / 审查工作（新建·任务·批次）/ 合规运营（影响·台账）/ 知识库 / 系统管理。

## mock 覆盖的端点（`frontend/dev-mock.mjs`，端口 8000）

- **认证**：`POST /auth/login`（任意账号密码 → mock-token）、`GET /auth/me`
- **驾驶舱**：`GET /impact/overview`（完整计数假数据）
- **任务**：`GET /tasks`（24 条模拟，支持 search/status/page 过滤）、`GET /tasks/1|15`、`GET /tasks/1/report`、`GET /tasks/1/results`、`POST /tasks`
- **复核**：`POST /results/bulk-confirm`、`POST /results/revert`、`GET /tasks/1/sign-off`、`POST /tasks/1/sign-off`
- **AI 助手**：`POST /ai/tasks/1/ask`、`/ai/tasks/1/summary`、`/ai/results/{1,2,3}/rewrite`、`/ai/results/{1,2,3}/verdict-advice`
- **其他**：`GET /system/monitor`、`GET /notifications`、`GET /regulatory-updates` 等

**未匹配的路径会 fallback 返回 `{items: [], total: 0}`**——所以即使某页 mock 覆盖不全，
页面也能渲染出空态，不会白屏。

## 设计 tokens 基线（2026-10-07 全局视觉升级后）

视觉语言：**纸墨金铜（Editorial 方向）**——墨黑工作台 + 纸白内页 + 金铜强调。

### 色彩

| token | 亮色主题 | 暗色主题 | 说明 |
|---|---|---|---|
| `--el-color-primary` | `#1d1913`（墨） | `#c8963c`（金） | **主色双面性**：纸上的墨 / 暗处的光 |
| `--app-accent` | `#c8963c` | 同 | 金铜：激活指示/关键装饰（唯一强调色）|
| `--app-accent-deep` | `#8a6410` | `#c8963c` | 链接等需达对比度的场景 |
| `--app-bg` | `#f5f2ea` | `#14110d` | 页面底（暖纸 / 暖墨）|
| `--app-surface` | `#fffdf9` | `#1c1813` | 卡片（纸白 / 暖深）|
| `--app-ink` | `#14110d` | 同 | 侧栏 |
| 圆角 | base 6px / card 10px | 同 | 印刷品的方直感 |

**风险语义色（红/橙/绿）保持独立**，不与金铜混用；金铜与 warning 橙的区分靠色相
（金铜偏土黄褐、warning 偏橙）。

### 关键对比度（实测值，改动 token 后须复核）

- 亮色：墨黑/纸白 **17.22** · regular 11.74 · secondary 5.50 · placeholder **4.53** ·
  链接金铜 5.29 · 按钮（白字 on 墨黑）17.49 · 选中态暖金底 14.92
- 暗色：纸白/暖墨 16.27 · 金铜 on 暖墨 7.07 · 按钮 hover（暖黑 on 金铜）6.95

### 组件约定

- **主按钮**：墨黑常态 → **金铜 hover（暖黑字）**（`index.scss` 内覆写，暗色下 hover 用
  `--el-color-primary-dark-2`）
- **卡片标题 / 页面标题**：宋体系（`--app-font-display`）+ 正字距（中文标题 0.04–0.06em）
- **侧栏激活项**：金铜竖线（3px）+ 暖金 14% 底 + 金铜文字（仿公报目录当前条目）
- **登录页**：固定纸墨语言（不随主题），作用域内锁死 EP 文本变量防暗色污染

## 已知坑（视觉验证相关）

- 前端 `npm run dev`（Vite dev）在本机沙箱下会因预构建清理触发
  `SAFE_DELETE_BULK_CONFIRM_REQUIRED` 而**起不来** → 用 `build + preview` 替代
- preview 只监听 IPv6 → 用 `localhost` 访问（`127.0.0.1` 返回 502）
- 页面有编排入场动画 → 截图前 `sleep 3`，否则拍到 opacity 0 的中间态

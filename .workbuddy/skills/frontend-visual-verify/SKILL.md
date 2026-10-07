---
name: frontend-visual-verify
description: 对本项目前端（Vue 3 + Element Plus）做视觉验证——起 dev-mock 假数据通道走通登录，用 agent-browser 驱动真实 Chromium 逐页截图与 DOM 检查，无需 MySQL/后端。当需要验收 UI 改动、排查样式破损、确认页面在现行设计 tokens 下的渲染，或用户要求"看一下效果/截图看看"时使用。
agent_created: true
---

# 前端视觉验证（agent-browser + dev-mock）

对本项目前端改动做**实机视觉验收**并产出截图证据。核心思路：用项目自带的
`frontend/dev-mock.mjs` 假数据 API 绕开 MySQL/后端依赖，用 `agent-browser`
驱动真实 Chromium——UI 改动因此可以在不启动数据库的前提下被亲眼验证。

## 何时使用

- 改动了 frontend 的样式 / tokens / 组件 / 布局后需要确认渲染效果
- 需要给用户产出可视化证据（截图）
- 排查"某个页面在某主题下样式破损"
- 用户说"看看效果""截个图""验收一下"

不适用：纯逻辑改动（跑 vitest 即可）、后端接口验证（那需要真数据库，
走 `.workbuddy/memory/` 里 2026-10-06 记录的端到端冒烟流程）。

## 核心工作流

### 1. 确认前端构建通过

```bash
cd frontend && npm run typecheck && npm run test && npm run build
```

视觉验证建立在构建成功之上；构建失败时先修，不要靠截图掩盖。

### 2. 起两个服务（均不碰数据库）

```bash
# 前端静态服务（构建产物）
cd frontend && npm run preview > /tmp/fcr-preview.log 2>&1 &   # → localhost:5173

# 假数据 API（README 官方"仅调前端 UI"通道；端口 8000 与 preview proxy 默认目标一致）
cd frontend && node dev-mock.mjs > /tmp/fcr-mock.log 2>&1 &    # → 127.0.0.1:8000
```

验证连通：`curl -s http://localhost:5173/api/v1/health` 应返回 mock 的 JSON。

**注意用 `localhost` 而不是 `127.0.0.1`**——本机沙箱环境下 IPv4 回环可能返回
502，IPv6（localhost 解析）正常。

### 3. agent-browser 操作（逐条命令都要 timeout 包一层）

```bash
timeout 60 agent-browser open http://localhost:5173
timeout 40 agent-browser set viewport 1440 900       # 设计基准视口（viewport 是 set 的子命令）
timeout 40 agent-browser snapshot -i                 # 取交互元素 ref
timeout 40 agent-browser fill @e6 "admin"            # ref 以实际 snapshot 输出为准
timeout 40 agent-browser fill @e7 "admin123"
timeout 40 agent-browser click @e5                   # 登录按钮（mock 下任意账号密码可登录）
sleep 5
timeout 40 agent-browser eval "location.pathname"    # 确认已跳转 /dashboard
```

一键脚本见 `scripts/verify_ui.sh`（封装：起服务检查 → 登录 → 逐页截图 → 归档）。

### 4. 截图与检查

```bash
sleep 3                                              # 等入场动画结束，必须
timeout 60 agent-browser screenshot --screenshot-dir /tmp/fcr-shots
```

- 截图后**用 Read 工具读 PNG 亲眼检查**（多模态），不要只看命令返回 ✓
- 需要 DOM 层面的确认时用 eval：
  ```bash
  timeout 40 agent-browser eval "getComputedStyle(document.querySelector('.x')).display"
  ```
- 切换主题验证暗色模式：
  ```bash
  timeout 40 agent-browser eval "localStorage.setItem('app-theme','dark'); location.reload()"
  ```
- 归档截图到项目：`docs/ui-verify-<date>/NN-页面名.png`

### 5. 收尾

```bash
timeout 30 agent-browser close     # 必须执行，避免僵尸 daemon 与 Chromium 进程
```

服务去留问用户（preview/mock 是轻量进程，留着方便用户自己点着看，但不要默认留）。

## 关键坑（都踩过，务必遵守）

1. **每个 agent-browser 命令都用 `timeout N` 包一层**。首次 `open` 会因 daemon
   冷启动握手长时间挂起（实测 13 分钟不返回）；包 timeout 后重试第二次即恢复。
2. **截图前 `sleep 3`**。页面有编排入场动画，动画未跑完时元素仍是 `opacity: 0`——
   过早截图会拍到"内容缺失"的假象（实测踩过：目录区看起来空的，DOM 检查
   opacity 已是 1，只是拍摄时机太早）。
3. **用 `localhost` 不用 `127.0.0.1`** 访问前端（见上，IPv4 可能 502）。
4. **`| tail` 管道会吞掉实时输出**。启动服务时若要读日志，重定向到文件
   （`> /tmp/xxx.log 2>&1`），不要接 `tail`。
5. **构建产物有 chunk 分割**：核对某个页面是否进了构建时，去 `dist/assets/`
   找对应 chunk（如 `LoginView-*.css`），不要只 grep 主 bundle。

## 本项目上下文

页面路由清单、mock 覆盖的端点、设计 tokens 基线（色彩 / 实测对比度）见
`references/project-context.md`。

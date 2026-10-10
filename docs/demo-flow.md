# 演示动线（八步）：从材料上传到整改闭环

一句话定位：把系统能力串成一条**可演示、可验收**的合规价值链——材料送审 →
双引擎审查 → 人工复核 → 签发放行 → 一键举证 → 影响监测 → 依据失效整改 → 复测闭环。
八步每一步都有 API 级断言（`scripts/demo/smoke_demo_flow.py`），
**合入 staging 后必跑**，是后续所有 PR 的部署验收步骤。

## 八步一览

| 步骤 | 动作 | 调用 | 体现的能力 |
|---|---|---|---|
| 1 | 登录 | `POST /auth/login` | 统一认证（JWT + 角色权限矩阵） |
| 2 | 上传 | `POST /documents/upload` | 材料入库（multipart，落盘 + 解析管线） |
| 3 | 审查 | `POST /tasks` → 轮询 `GET /tasks/{id}` | 规则 + LLM 双引擎，异步管线进度可见 |
| 4 | 人工复核 | `POST /results/bulk-confirm` | 低置信/高风险人工判定，待复核清零 |
| 5 | 签发 | `POST /tasks/{id}/sign-off` | 合规闭环收口（门槛：完成 + 零待复核，多次留痕） |
| 6 | 证据包 | `GET /tasks/{id}/evidence-pack` | 报告 + 结论生命周期 + 操作留痕，zip 内 **manifest SHA256** 可自验证 |
| 7 | 影响中心 | `GET /impact/overview` | 监管影响全域看板（整改/失效/巡检/高危材料计数） |
| 8 | 整改闭环 | 停用规则 → `stale/sync` → 决策 → `retest` | 依据失效反向定位 → 整改版升版 v2 → 复测通过**自动关闭** |

## 运行方式

```bash
# staging（默认；由 scripts/deploy/init_staging.py 初始化）
python scripts/demo/smoke_demo_flow.py

# 打本机 dev 栈（uvicorn 8000）
STAGING_API_BASE=http://127.0.0.1:8000 python scripts/demo/smoke_demo_flow.py
```

- 失败即红：任一步失败打印**失败步 + 响应体片段**，退出码 1（CI / 部署验收可直接判红）。
- 可调超时：`SMOKE_REVIEW_TIMEOUT`（默认 300s）、`SMOKE_RETEST_TIMEOUT`（默认 240s）——
  审查/复测含真实 LLM 调用，staging 冷启动较慢时放宽即可。
- 完整跑一遍约 3–6 分钟（两段真实审查管线）。

## 部署验收节奏（PR-4④ 固化）

审计（2026-10-10）发现"每 PR 合入后必跑"曾靠人工纪律、PR-6/7 合入时被积压——固化为明确 checklist：

**每个 PR 合入 main 后（写代码的人当天执行）**：

```bash
# 1) 重建镜像（PR 改了 src/ 前端/迁移/Dockerfile 任一才需要；层缓存命中约 1-5 分钟）
#    —— ASCII 路径 workaround 与增量同步方法见 docker/docker-compose.yml 顶部注释
# 2) 初始化 staging（幂等；PR 改了解析/向量数据才需要 --refresh-chroma）
python scripts/deploy/init_staging.py
# 3) 冒烟两连（顺序：快断言先行定位，八步看全链路）
python scripts/demo/smoke_staging.py          # 四断言，~5s
python scripts/demo/smoke_demo_flow.py        # 八步，3-6 分钟（含真实 LLM）
# 4) 结果记入 PR 描述（八步各步状态 + 耗时）
```

**八步含真实 LLM 调用无法进 CI 门禁**；CI 侧的自动化等价物是
`staging-smoke.yml`（workflow_dispatch 手动触发：构建镜像 + 容器内迁移 +
种子 + **四断言**——不含 LLM 步骤），用于发版前的环境级验证。

**积压处理**：万一某 PR 跳过了（如 hotfix 抢时间），必须在下一个 PR 的验收中
**补跑并显式声明"覆盖至上一提交"**——不允许无冒烟的连续合入超过 1 个 PR。

## 设计说明（为什么这么写）

- **幂等可重复**：每次运行新建文档/任务/材料（名称带时间戳），不依赖前次状态；
  第 8 步结束时**复原环境**（停用的规则重新启用、演示材料归档）——失败也会尽力复原（finally），
  重复执行不会污染演示数据。
- **第 2 步材料刻意含违规表述**（保本保息/稳赚不赔/预期年化收益）：保证第 4–6 步
  有真实结论可复核、可签发、可入包，而不是空跑流程。
- **材料正文不放长数字串**：内置 PII 检查对 13–19 位连续数字做 Luhn 校验，
  偶合通过即判"疑似银行卡号"——14 位时间戳运行标记曾实测中招（2026-10-08），
  故运行标记只出现在**文件名**（正文不含数字串）。
- **第 8 步自建"依据失效链"**：从第 3 步实际命中的规则里取一条停用（PUT `/rules/{id}`），
  再用同文档登记材料台账 → `stale/sync` 必然命中该材料（同步响应 `highlight_ids` 断言），
  随后走"需整改 → 上传整改版（v2）→ 复测"全链路；整改版文本为规范表述
  （开发环境已预检：规则零命中、真实管线零违规），确保走"**通过 → 自动关闭**"路径。
- **证据包校验复用包内 manifest**：逐文件核对 `sha256` 与 `bytes`——同时验证
  "包自身完整性承诺"（文件被事后篡改即可发现）与下载链路完整性。

## 与既有冒烟的关系

| 脚本 | 定位 | 断言数 |
|---|---|---|
| `scripts/demo/smoke_staging.py` | 部署可用性（起没起来、连不连得通、前端反代） | 4 |
| `scripts/demo/smoke_demo_flow.py` | 业务动线（八步全链路，含整改闭环） | 8 步（含 6 项子断言） |

部署验收顺序：`init_staging.py`（起栈+种子）→ `smoke_staging.py` → `smoke_demo_flow.py`。

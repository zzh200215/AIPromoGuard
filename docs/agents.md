# Agent 与组件合约（Agent Registry）

本系统是**基于 LangGraph 的受控多 Agent 合规审查工作流**：专业审查 Agent 负责语义判断，
确定性工具负责字面检测与溯源，协作控制节点负责路由、融合与人工交接。本文按五类组件
给出职责合约——每项组件明确七件事：负责什么/不负责什么、输入、可调用的工具、输出
Schema、何时交接、失败与降级、是否允许自动通过、用什么指标衡量。

> 分类原则：不以"是否叫 Agent"命名，而以"是否有独立任务、工具调用、结构化输出、
> 交接决定"四标准判定。确定性工具不包装成 Agent；业务闭环（影响中心）是工作流而非 Agent。

## 一、专业审查 Agent（LLM 驱动，有自主判断与工具调用）

### 语义审查 Agent（`llm_scan` 节点）

| 合约项 | 内容 |
|---|---|
| 职责边界 | 负责：变体化/语义化违规的识别（换说法的保本承诺、夸大宣传、适当性误导、披露缺失）；不负责：字面红线（规则引擎已覆盖）、产品设计与投资策略评价 |
| 输入 | 文档块（blocks）、召回法规条款（matched_articles，含文号/日期）、领域 |
| 工具 | 真 Function Calling：审查中主动调 `search_regulations` 查证再判定（成本护栏：调用次数上限） |
| 输出 Schema | `{type(禁止性/限制性/披露性), issue, original_text(原文摘录), regulation(法规名+条款号), reason, suggestion, severity, confidence}`；非法枚举/缺失关键字段自动丢弃（幻觉抑制） |
| 交接条件 | 输出经 conflict_resolve 与规则命中做 span 重叠：交叉命中→hybrid（升级高置信），单独命中→llm（"建议关注"） |
| 失败与降级 | LLM 无 Key/调用失败→空 findings 继续走规则路；模型 fallback 链；输出不合法自纠错重试一次 |
| 自动通过 | 不允许（纯 llm 一律进人工复核） |
| 评估指标 | Judge 结论判分精度 **95.7%**、span 口径召回 100%（71 例变体集）；基线对照见 [benchmark.md](benchmark.md) |

### 法规检索自评子流程（P3 Agentic RAG，可选 `workflow.agentic_retrieval`）

| 合约项 | 内容 |
|---|---|
| 职责边界 | 负责：判断召回条款对文档的覆盖充分性、生成监管术语化补检查询；不负责：直接判定违规 |
| 输入 | 文档全文、基础召回条款 |
| 工具 | 复用混合检索（自评产生的查询再走 RRF 融合） |
| 输出 Schema | `retrieval_meta = {rounds, queries[], added, sufficient, usage}` |
| 交接条件 | 补检结果与基础召回 RRF 融合后交回语义审查 |
| 失败与降级 | LLM 未配置/失败→保持基础召回；轮次/查询数/无新增三重护栏 |
| 自动通过 | 不适用（检索子流程） |
| 评估指标 | judge 检索相关性 48.7%（观察口径，未进门禁） |

## 二、确定性工具（零 LLM，可解释可复现）

### 规则引擎（`rule_scan` 节点 + `src/core/rule_engine`）

| 合约项 | 内容 |
|---|---|
| 职责边界 | 负责：字面红线（禁用词/绝对化表述/适当性话术）的确定性检测；不负责：换说法的语义违规 |
| 输入 | 文档块、激活规则库（82 条，含 26 条挖掘规则） |
| 工具 | regex/keyword matcher + 否定语境抑制 + 每规则阈值 |
| 输出 Schema | `RuleHit{rule_id, rule_name, matched_text, char_start/end, confidence, page/paragraph}` |
| 交接条件 | 命中→conflict_resolve（规则优先采信）；落库时经 `_citation_for_rule` 反查规则-法规关联表回填条款级溯源 |
| 失败与降级 | 非法 regex 预编译拦截（不入库）；规则库为空→空结果不阻塞 |
| 自动通过 | 允许（rule/hybrid 高置信自动确认，`confirmed_by=0`）——但 evidence_supported=False 的引用幻觉除外 |
| 评估指标 | 回归门禁 100%/0%；逐规则隔离门禁（自证召回 100%+自身零误报）；变体集贡献见 [benchmark.md](benchmark.md) 消融表 |

### 证据核验关卡（`src/services/evidence`，零 LLM）

| 合约项 | 内容 |
|---|---|
| 职责边界 | 负责：核验 llm/hybrid 结论引用的法规是否真在召回条款中（含泛引检测）；不负责：核验规则路（其依据是规则-法规关联表的结构化溯源） |
| 输入 | finding 的 regulation 自由文本 + 召回条款列表 |
| 工具 | 书名号名匹配 + 子串退化匹配（确定性） |
| 输出 Schema | `evidence_supported ∈ {True, False, None}`（None=未引用/召回为空，不参与统计） |
| 交接条件 | False → Markdown 报告标"⚠️证据待核" + 强制人工复核（不参与自动确认） |
| 失败与降级 | 纯函数无失败路径 |
| 自动通过 | 只允许 True/None 参与；False 一律人工 |
| 评估指标 | 引用可支撑率 62.1%（judge 口径，71 例）——引用可能正确但不在召回上下文，故 False 的处置是人工复核而非直接丢弃 |

### 其他确定性工具

| 组件 | 职责 | 输出/指标 |
|---|---|---|
| 解析器（parsers：txt/docx/pdf/ocr） | 材料→文本块+位置 | 块结构；OCR 质量列入已知限制 |
| 影响分析（`src/core/impact/analysis`） | 新规→受影响规则定位+存量材料风险预扫打分 | 结构化影响评估；全程无 LLM 参与决策 |

## 三、RAG 工具与子流程

| 组件 | 职责 | 工具/数据 | 输出 | 失败与降级 |
|---|---|---|---|---|
| 混合检索（`regulation_match`） | 条款级召回：语义+关键词 RRF 融合，生效法规优先，可选 rerank | ChromaDB+fastembed / 规则匹配 | `matched_articles[{article_id, regulation_name, article_no, content, status, 文号/发布/生效日期}]` | 混合失败→纯关键词回退 |
| 图谱召回（P2 GraphRAG，`graph_service`） | "违规模式→条款"多跳：规则引擎实扫命中的模式经条款级 VIOLATES 边展开为第三路 | Neo4j | 图谱条款列表（RRF 并入） | Neo4j 未启用/失败→跳过图谱路 |
| 处罚案例佐证（`risk_assess` → Neo4j） | 相似历史罚单检索 | Neo4j 案例网络 | `similar_cases[{case_name, penalty_org, similarity, ...}]` | 图谱未启用→无佐证不阻塞 |

## 四、协作控制节点（编排层）

| 节点 | 职责 | 交接/分流 |
|---|---|---|
| `classify` | 领域识别（配置驱动关键词打分） | 条件路由到 banking/fund/insurance 子图，general 兜底 |
| `conflict_resolve` | 信任分级融合：rule 采信 / llm 建议关注 / hybrid 交叉确认；证据核验交接 | merged_findings → human_review |
| `human_review` | 人工复核关卡：`interrupt()` 暂停 + MySQL checkpoint 续跑；auto-confirm 分流（高置信 rule/hybrid 自动确认 `confirmed_by=0`，其余 pending） | 高风险/意见分歧/证据不可支撑→人工裁决；人可确认/驳回/翻案（全程审计留痕） |
| `risk_assess` | 风险定级打分卡（类型×来源×置信度，经验权重，已知限制） | 定级结果进报告与台账 |
| `report` | JSON/Markdown/PDF 报告生成落盘 | `evidence_supported=False` 在报告中可见 |

## 五、业务工作流（场景，非 Agent）

三条业务链对应 README 中三张架构图，各组件在链中的位置如下：

1. **发布前联合审查**（README 架构图）：classify 路由 → 混合检索+图谱召回（法规证据）→ 规则引擎 ∥ 语义审查并行 → 证据核验 → 信任分级融合 → 风险定级 → 人工复核关卡 → 报告。多视角意见（规则=字面模式、语义=变体话术、适当性=适配误导）在 conflict_resolve 汇合，冲突以 hybrid 升级与"建议关注"分级表达，最终由人工裁决。
2. **新法规影响分析**（README 影响中心图）：监管动态轮询 → 影响分析（确定性预扫打分）→ 人工确认影响范围 → 批量复审（复用联合审查链 + interrupt 关卡）→ 台账回写/整改清单。
3. **整改复测闭环**（README 影响中心图后半）：业务部门上传整改版（台账升版）→ 全链路复测（新增违规同样会被检出）→ 复测通过自动销项 → 规则 draft → publish 的版本管理。

## 六、评估口径总览

| 口径 | 工具 | 数字（2026-08-30） |
|---|---|---|
| 字面红线（规则路） | 回归门禁 + 逐规则隔离门禁 | 100% / 0.5%（gate 口径 0.98/0.02） |
| 语义层（全链路 vs 裸 LLM） | baseline_compare | 召回 97.8% vs 97.2%，误报 1.0% vs 9.3% |
| 组件贡献 | ablation.py（71 例/170 标注点） | 三臂召回均 100%；规则路检出 728→179（纯 LLM）放大 4 倍；图谱路本集召回贡献 0（与规则路信息重叠，冗余兜底价值） |
| 结论语义判分 | judge.py | 判分精度 95.7%（303 true / 9 FP / 1 依据错误） |
| 引用可支撑 | evidence（生产内联）+ judge（观察） | 62.1%（judge 口径，False→人工复核不丢弃） |
| 人机协同 | review_adoption.py | 漏斗 841 结论/84 自动分流；采纳率待真实使用积累 |

## 七、成本归因与待核验清单

两类报告内建的可观测产物，均为确定性逻辑（零 LLM 消耗）：

- **成本归因**：LLM 客户端逐次采集 `resp.usage`，节点经 `state.llm_usage` reducer 累加（llm_scan 扫描 + agentic 检索两处计入），报告生成时按牌价表换算预估金额（`src/core/llm/pricing.py`，家族子串匹配，未收录模型只报 token）。用量与预估随报告 JSON/Markdown 落盘并持久化到 `review_tasks.llm_usage`（API TaskOut 同步暴露）——每次审查"花了多少 token、约多少钱"可追溯。
- **待人工核验清单**：报告第五节聚合机器无法闭环背书的存疑项——证据门禁判 False（引用法规未命中召回条款）、LLM/hybrid 无引用或召回为空（自动核验未覆盖）、适当性判定（需产品风险等级与目标客群材料佐证）。清单按风险降序，空时显式声明"无"，与复核队列（`pending_confirm`）互补：清单面向"补充证据/材料"，队列面向"确认/否决结论"。

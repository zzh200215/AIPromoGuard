# 评估闭环（方向④）：标注集 + 门禁 + CI

## 标注集
- **合成基准集** `scripts/evaluate/eval_cases.json`：50 案例 / 139 标注点 / banking·fund·insurance 三领域，
  含否定语境负面案例。人工标注的回归基线，rule 引擎当前 **100% 召回 / 0% 误报**。
  ⚠️ 口径澄清：该集与 rules.json 的 50 条规则存在构造对应关系（每条规则都有对应标注案例），
  **本质是回归测试集**（防规则改动退化），不是泛化能力评估——泛化请看下面的变体集。
- **真实标注集机制** `scripts/evaluate/export_labels.py`：把真实人工复核
  （`confirmed_by>0`，排除系统自动确认）导出为 `real_cases.json`（同格式）。
  随真实使用增长——"合成样本 → 真实标注集"的迁移路径：
  ```
  python scripts/evaluate/export_labels.py
  python scripts/evaluate/evaluate.py --engine rule --cases scripts/evaluate/real_cases.json
  ```
  口径：全 confirmed 任务 → 正例；全 false_positive 任务 → 负面案例（`ground_truth=[]`）；
  混合任务跳过。自动排除 description 带测试标记（"测试人工复核"/"E2E"/"e2e"）的记录，
  与数据清理口径一致。**人工合并进 eval_cases.json，不自动覆盖。**

## 变体集（held-out 泛化评估，2026-08-16）
- **构造方法**：`scripts/evaluate/variant_cases.json`（19 案例 / 14 违规标注点 / 5 合规负样本）。
  由 LLM 对 seed 违规模式做**保义改写**，刻意绕开规则库全部字面触发词
  （不含 保本/保息/保收益/刚性兑付/预期收益/零风险/稳赚/兜底/翻倍 等），
  与 rules.json **无构造对应关系**；合规负样本用于测全链路误报。
- **为什么需要它**：eval_cases.json 与规则库一一对应（构造使然），在上面跑出 100%
  只能证明"没有回归"，不能证明"泛化"。变体集模拟真实世界里"换个说法"的违规话术。
- **实测结果**（2026-08-16，qwen-plus）：

  | 引擎 | 召回率 | 误报率 | 说明 |
  |---|---|---|---|
  | 规则引擎单独 | **0.0%**（0/14） | 0.0% | 保义改写全部绕开字面规则——规则引擎的泛化边界 |
  | 全链路（规则+LLM） | **100.0%**（14/14） | **0.0%** | LLM 引擎补回全部漏检，检出全部来自 `llm` 来源；合规负样本零误报 |

- **结论**：这组对照是双引擎架构必要性的直接实证——规则引擎提供确定性/可解释/零成本，
  但只认字面模式；LLM 引擎承担语义泛化（改写、黑话、隐晦承诺），prompt 中的合规披露
  白名单保证了补召回不引入误报。复现：
  ```
  python scripts/evaluate/evaluate.py --engine rule --cases scripts/evaluate/variant_cases.json
  python scripts/evaluate/evaluate.py --engine full  --cases scripts/evaluate/variant_cases.json
  ```
  （full 需要 DASHSCOPE_API_KEY；LLM 非确定性，重跑召回允许小幅波动，结论方向稳定。）

## 门禁
- **pytest** `tests/unit/test_eval_gate.py`：跑 `evaluate.py --engine rule --min-recall 0.98 --max-fpr 0.02`，
  跌破即失败。rule 引擎是确定性逻辑、基线 100%/0%，阈值刻意高于 PRD §9 的全管线目标（召回 ≥ 91%）。
  依赖 DB（skipif 保护），需先 `scripts/init_data/import_rules.py` 灌规则。
- **本地包装** `scripts/evaluate/gate.sh`：`bash scripts/evaluate/gate.sh`，退出码即门禁结果。
  Docker 环境：`docker exec fcr-api python scripts/evaluate/evaluate.py --engine rule --min-recall 0.98 --max-fpr 0.02`。
- **CI** `.github/workflows/eval-gate.yml`：push/PR 自动拉起 MySQL（复用 `docker/init-scripts/init_mysql.sql` schema）
  → 灌规则 → 跑门禁测试。**仓库当前未推送（无 remote），推送后首次生效。**
  runner 为 ASCII 路径，不受本地 buildx 中文路径 bug（docker/buildx#3972）影响。
- 变体集**不做门禁**（CI 无 LLM Key，full 引擎会降级为纯规则导致必然失败），
  仅作为本地/人工效果评估与叙事素材。

## 挖掘规则门禁（数据飞轮，2026-08-29）

法规规则挖掘（`scripts/crawl/mine_rules_from_regulations.py`）产出的 draft 规则在进入审查引擎前要过**四道关卡**，每道都是引擎级实证而非人工判断：

1. **regex 预编译**：引擎对非法 pattern 静默返回空（漏检），解析层预编译拦截（实测拦截率约 5%）。
2. **引擎冒烟测试**：LLM 必须给出违规正例（必须命中），反例由系统确定性构造——否定变体（"本产品不"+命中片段，验证否定语境抑制放行合规声明）+ 每领域 6 句内置合规声明语料（命中即拒绝）。实测把"裸 `预期收益率`"这类会误伤合规披露的粗规则全部拦下。
3. **语义查重**：与库内规则（含 draft）做可匹配字面量（regex 分支 + keyword 词）重叠比对，≥60% 视为语义重复——同一"保本保收益"主题在 N 部法规里反复出现，靠它收敛。
4. **对抗门禁**（`scripts/evaluate/gen_variants.py`）：对激活规则生成"保义改写"样本（gt 指向该规则）+ 合规负样本，逐规则隔离跑引擎——目标规则对自身标注点召回须 100%、对负样本须零命中；不过关自动退回 draft。通过后再跑回归基准集（gate 口径 0.98/0.02），确保新规则不破坏既有召回/误报。

**首轮实测（32 条 draft）**：12 条 LLM 正例自不命中、9 条语义重复、5 条合规语料误伤、5 条同名、1 条否定抑制失效被拦；激活的 27 条中 4 条在对抗门禁退回、3 条在回归集产生 6 个误报退回——**最终 25 条服役，回归门禁 100%/0% 保持绿**。

**方法论教训（误报归因）**：对抗门禁第一版复用 evaluate 的 case 级指标，合规负样本触发的*其他规则*（如手工规则的"过往业绩"关键词命中合规声明"过往业绩不预示未来表现"）被记到*目标规则*头上，导致 7 条好规则被误退回。修正为逐规则隔离扫描（只用目标规则跑 case），归因才准确——这也暴露了库内既有规则对"提及即命中"类关键词的泛化误报问题，留待 reflow_labels 的真实复核数据治理。

**已激活挖掘规则种子**：`scripts/crawl/mine_rules_from_regulations.py export-approved` 导出 `rules_mined.json`（与 rules.json 同 schema），已接入 CI 种子配方，保证 CI 环境与本地规则集一致。

## LLM-as-a-Judge 语义判分（P4，2026-08-29）

span 重叠口径对规则引擎是精确的（字面命中），但对 full 引擎系统性低估——LLM findings
会改写/概括原文，字符级重叠经常失配；变体集又刻意绕开规则触发词，其 full 引擎效果
此前只有人工口径。`scripts/evaluate/judge.py` 引入 LLM 复核员做**语义级判分**（本地工具，
observe-only，不进 CI 门禁）：

- **结论判分**：逐条 finding 判 `true_violation / false_positive / wrong_basis`（举证责任
  在系统，拿不准判误报）→ judge_precision
- **引用可支撑率**：确定性检查（零 LLM）——结论引用的法规是否出现在召回条款中，
  无书名号时退化为子串匹配，"根据监管规定"式泛引记为不可支撑
- **检索相关性**（RAGAS 式）：召回条款与文档主题逐条判定相关/无关 → context_precision，
  并输出文档涉及但未召回的监管主题（missing_topics）
- **span 口径对照**：同案例并报 span_recall，两种口径可并读

用法：`python scripts/evaluate/judge.py --limit 10 --out judge_report.json`（需 API key；
`--engine rule` 可复核规则引擎输出）。首轮 smoke（变体集 3 例，full 引擎）：judge_precision
1.0（3 true / 0 FP）、span_recall 1.0、引用可支撑率 1.0、检索相关性 0.4-0.8，成本约
750 token/例——判分本身便宜，贵的是 full 引擎扫描（每案例全 workflow）。

诚实边界：judge 自身是 LLM，其判分无人工金标准校准（首轮人工抽检一致后才可作为
软参考）；judge 与被评对象同源（同一家模型自评存在偏乐观风险），后续可换异构模型
当复核员；该指标不进 gate，仅作 full 引擎效果观测与回归对比基线。

## 数据卫生
- 人工复核统计（feedback / 规则精调建议）只计 `confirmed_by>0` 的真实人工数据；
  系统自动确认（`confirmed_by=0`）不计入（避免循环论证）。
- 2026-08-12 已清理 49 条测试期人工复核记录（task 6-228，description 均含测试标记），
  rule#2「禁止刚性兑付承诺」此前基于这些噪声生成了误导性停用建议，经核实**未应用**，规则原样保留。
- 约定：E2E/回归脚本创建的复核数据必须自清理（如 `DELETE FROM review_results WHERE task_id = ...`）。
- ⚠️ **路径反斜杠陷阱**：DB 的 `document_path` 存的是 Windows 风格相对路径（`data\uploads\doc_x.txt`），
  即使运行在 Linux 容器内也如此（历史数据沿用）。做文件清理时取文件名必须归一化：
  `dp.replace("\\", "/").split("/")[-1]`，**不能**用 `Path(dp).name`（Linux 下会把整串当文件名，导致真实引用文件被误判为孤儿）。
  2026-08-12 曾因该 bug 误删 88 个演示源文件（属无报告残留任务），已按用户决定删除对应任务记录收尾，终态 125 任务/40 文件完全一致。

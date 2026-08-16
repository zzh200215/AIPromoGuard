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

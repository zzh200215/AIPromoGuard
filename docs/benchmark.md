# 效果基准报告（Benchmark）

一句话结论：**规则引擎在字面被绕开后召回归零，全链路（规则+检索+LLM）把召回补满且不引入误报**——双引擎+检索架构的必要性有对照实验支撑，不是架构摆设。本文是该结论与"人机协同"价值的统一数据出口，全部数字可由下列命令复现。

## 1. 引擎对照实验（架构必要性）

**指标口径**：标注点召回率（检出与标注互为子串即命中）+ 检出误报率（含 negative_ground_truth 负样本：合规披露表述被命中即计误报）。样本为 held-out 变体集——对全部规则触发词做保义改写，刻意绕开字面匹配。

**历史实测**（19 案例版变体集，2026-08，见 [evaluation.md](evaluation.md)）：

| 引擎 | 召回率 | 误报率 | 说明 |
|---|---|---|---|
| 规则引擎单独 | **0.0%** | 0.0% | 字面模式被改写后完全失效（泛化边界实证） |
| 全链路（规则+检索+LLM） | **100.0%** | **0.0%** | 漏检 100% 来自 LLM 语义路，合规负样本零误报 |

**三列对照**（44 案例版变体集，`baseline_compare.py`）：

| 引擎 | 召回率 | 误报率 | 检出 | 误报数 | 命中标注 |
|---|---|---|---|---|---|
| 规则引擎 | 0.0% | 0.0% | 0 | 0 | 0 / 89 |

> 裸 LLM 直查（无检索、无规则库）与全链路两列待 DashScope 账户恢复后补全：
> `python scripts/evaluate/baseline_compare.py --runs 2 --out baseline_report.json`
> 脚本与口径已就绪并完成管线验证（规则列如实反映"改写绕开字面 → 0 命中"的泛化边界）。

## 2. 人机协同漏斗（复核采纳率）

金融合规的最终价值口径不是模型分数，而是**AI 结论被合规人员接受/纠正的比例**（`review_adoption.py`，口径与 `/results/feedback-stats` 一致：人工复核 = `confirmed_by>0`，系统自动确认不进分母）：

| 漏斗 | 数量 | 占比 |
|---|---|---|
| 全部审查结论 | 841 条 | 100% |
| 系统自动确认（规则/混合高置信分流） | 84 条 | 10.0% |
| 待人工复核（LLM 单独命中/低置信） | 757 条 | 90.0% |

- 人工采纳率：**待真实使用积累**（测试期复核数据已按数据卫生约定清理，不用脚本数据冒充人工判断）。
- 翻案率：confirm 判定留痕（审计 `result.confirm`：before_status / before_auto_confirmed / verdict）自 2026-08-29 起积累，翻案 = before_status != verdict，其中"纠错自动确认"单独计数。

## 3. 检索与结论质量（LLM-as-a-Judge，observe-only）

[judge.py](../scripts/evaluate/judge.py) 对审查结论做语义判分（true_violation / false_positive / wrong_basis，举证责任在系统）、引用幻觉检查（结论引用的法规是否在召回上下文中，确定性零 LLM）、RAGAS 式上下文精度与缺失主题。运行：

```bash
python scripts/evaluate/judge.py --limit 10 --out judge_report.json
```

## 4. 质量门禁（CI 三件套）

回归基准集（50 案例/139 标注点）+ 变体集（44 案例/89 标注点）逐规则隔离扫描：自证召回 100% + 自身零误报 + 不破坏回归集（gate 口径 0.98/0.02），不达标规则自动退回 draft。`scripts/evaluate/gate.sh`，GitHub Actions 每次提交运行。

## 复现命令

```bash
# 引擎对照（需 DASHSCOPE_API_KEY；规则列无需）
python scripts/evaluate/baseline_compare.py --runs 2 --out baseline_report.json

# 复核漏斗与采纳率
python scripts/evaluate/review_adoption.py --json adoption_report.json

# Judge 语义判分
python scripts/evaluate/judge.py --limit 10 --out judge_report.json

# 质量门禁
bash scripts/evaluate/gate.sh   # 解释器不对时：PYTHON=/path/to/python bash scripts/evaluate/gate.sh
```

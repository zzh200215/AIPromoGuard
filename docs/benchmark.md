# 效果基准报告（Benchmark）

一句话结论：**召回与裸 LLM 直查持平的前提下（97.8% vs 97.2%），全链路把误报率从 9.3% 压到 1.0%（约降 89%）**；同时规则引擎以零 token 成本贡献 77% 的确定性检出。裸 LLM 的短板不是漏检，而是把合规的风险披露表述判成违规——这正是规则库 + 信任分级融合的价值。本文是该结论与"人机协同"价值的统一数据出口，全部数字可由下列命令复现。

## 1. 引擎对照实验（架构必要性）

**指标口径**：标注点召回率（检出与标注互为子串即命中）+ 检出误报率（含 negative_ground_truth 负样本：合规披露表述被命中即计误报）。样本为 held-out 变体集（44 案例 / 89 标注点 / 25 条合规负样本）。

**本次实测（2026-08-29，`baseline_compare.py --runs 2`，naive 为两次独立运行取均值）**：

| 引擎 | 召回率 | 误报率 | 检出 | 误报数 | 命中标注 |
|---|---|---|---|---|---|
| 规则引擎单独 | 84.3%* | 0.0% | 384 | 0 | 75 / 89 |
| 裸 LLM 直查（run1） | 96.6% | 9.8% | 102 | 10 | 86 / 89 |
| 裸 LLM 直查（run2） | 97.8% | 8.8% | 102 | 9 | 87 / 89 |
| 全链路（规则+检索+LLM） | **97.8%** | **1.0%** | 500 | 5 | 87 / 89 |

*规则引擎的整体召回要按样本来源拆开看——变体集由两组设计目标不同的样本构成：

| 样本组 | 案例 | 标注点 | 规则引擎召回 | 说明 |
|---|---|---|---|---|
| `var_*`：对全部规则触发词做保义改写、刻意绕开字面 | 19 | 14 | **0.0%** | 规则引擎的泛化边界实证（0 检出） |
| `mined-*`：挖掘规则的锚定变体，验证规则自身可达性 | 25 | 75 | 100.0% | 384 条检出零误报，确定性承担字面红线 |

三个读数：

1. **误报率降一个数量级**（9.3% → 1.0%）：裸 LLM 把合规负样本（"过往业绩不预示未来表现"类披露）判成违规，全链路的规则白名单 + 信任分级把这类误报拦住；
2. **召回持平**（97.8% vs 97.2%）：语义路补回 `var_*` 组规则完全够不到的漏检，没有牺牲泛化；
3. **确定性承载**：77% 的检出（384/500）来自规则引擎，可解释、可复现、零 token 成本——LLM 只在规则够不到的语义层发挥不可替代的作用。

**历史实测**（19 案例版变体集，2026-08，见 [evaluation.md](evaluation.md)）：当时变体集只含绕字面样本，规则引擎召回 0.0%、全链路 100.0% / 0.0% 误报——与上表 `var_*` 组的 0% 读数一致，口径未变。

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

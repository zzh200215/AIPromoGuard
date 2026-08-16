#!/usr/bin/env bash
# 方向④评估门禁 · 本地包装：跑 evaluate.py 干跑 + 指标门禁，退出码即结果（0 通过 / 1 失败）。
#
# 用法:
#   bash scripts/evaluate/gate.sh                        # 默认 rule 引擎，门禁 0.98 / 0.02
#   bash scripts/evaluate/gate.sh --engine full          # 完整 LLM 管线（需 DASHSCOPE_API_KEY）
#   bash scripts/evaluate/gate.sh --min-recall 0.91      # 覆盖召回门槛
#   PYTHON=~/venv/bin/python bash scripts/evaluate/gate.sh   # 指定解释器
#
# 依赖: DB 已启动且规则已灌入（scripts/init_data/import_rules.py）。
# Docker 环境替代: docker exec fcr-api python scripts/evaluate/evaluate.py --engine rule --min-recall 0.98 --max-fpr 0.02
#
# 阈值说明: PRD §9 的「召回率 ≥ 91%」是全 LLM 混合管线目标；
# rule 引擎是确定性逻辑、基线 100%/0%，门禁收紧到 0.98/0.02 用于抓规则改动回归。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
PYTHON="${PYTHON:-python}"

cd "$REPO_ROOT"

# 默认走 rule 引擎（快、无 LLM key 依赖）；用户命令行参数追加在后，
# argparse 取最后一次出现，可显式覆盖 engine / 阈值（如 --engine full 或 --min-recall 0.91）。
declare -a EXTRA=(--engine rule --min-recall 0.98 --max-fpr 0.02)
while [[ $# -gt 0 ]]; do
  EXTRA+=("$1")
  shift
done

"$PYTHON" scripts/evaluate/evaluate.py "${EXTRA[@]}"

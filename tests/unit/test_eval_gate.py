"""方向④评估门禁：把 evaluate.py 干跑挂进 pytest 测试套件。

规则引擎是确定性逻辑（无 LLM），基线 100% 召回 / 0% 误报（50 案例 / 139 标注点），
因此门禁收紧到 min_recall=0.98 / max_fpr=0.02 抓回归——任何规则改动让指标跌破即失败。

注意：PRD §9 的「召回率 ≥ 91%」是全 LLM 混合管线目标（评估门槛 _scan_full），
这里只门禁 rule 引擎（快、无 key 依赖），阈值刻意高于 PRD。

依赖真实 DB（skipif，同 test_rule_tuning）：evaluate.py 需从 rules 表加载生效规则。
"""

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from src.infrastructure.database.mysql import SessionLocal

MIN_RECALL = 0.98
MAX_FPR = 0.02
REPO_ROOT = Path(__file__).resolve().parents[2]


def _db_ready() -> bool:
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_rule_engine_eval_gate():
    """规则引擎干跑评估必须通过门禁（当前基线 100%/0%，阈值 0.98/0.02）。"""
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "evaluate" / "evaluate.py"),
            "--engine",
            "rule",
            "--min-recall",
            str(MIN_RECALL),
            "--max-fpr",
            str(MAX_FPR),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",  # evaluate.py 输出强制 UTF-8，Windows 默认 GBK 会解码失败
        errors="replace",
        timeout=300,
    )
    # 失败时把评估输出打出来便于定位回归点
    if result.returncode != 0:
        print(result.stdout[-4000:])
        print(result.stderr[-2000:])
    assert result.returncode == 0, (
        f"评估门禁未通过（min_recall={MIN_RECALL}, max_fpr={MAX_FPR}），见上方输出"
    )

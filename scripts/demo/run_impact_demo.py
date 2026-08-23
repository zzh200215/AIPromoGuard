"""一键演示：基金销售宣传合规影响分析全链路（CLI，面试可跑）。

用法（仓库根目录，需 MySQL/向量库可用）:
    python scripts/demo/run_impact_demo.py             # 预检失败则提示后退出
    python scripts/demo/run_impact_demo.py --reindex   # 向量库异常时自动重建索引

链路（模拟一名合规人员的完整操作）:
  1. 监管情报 → 触发影响分析（2 规则 / 10 材料 / 3高 3中 4低）
  2. 人工确认影响范围（沉淀规则-法规关联）
  3. 一键创建批量复审（默认圈选高/中风险 6 份）
  4. 等待审查完成：双引擎跑批，人工复核关卡自动续跑（全部确认）
  5. 批次终态自动回写台账并生成整改清单
  6. 记录整改决策
  7. 规则新版本：起草 → 修改 → 发布（旧版自动停用）

跑完保留演示数据，可打开前端对照查看；重复执行会先重建演示数据。
"""

import logging
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台默认 GBK

from scripts.demo.seed_impact_demo import seed_demo  # noqa: E402

logging.disable(logging.INFO)  # 演示输出只留警告以上，SQL/应用日志不刷屏

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from src.api.main import app  # noqa: E402
from src.infrastructure.database.mysql import SessionLocal  # noqa: E402

client = TestClient(app)
RISK_LABEL = {"high": "高", "medium": "中", "low": "低"}
WAIT_TIMEOUT_SECONDS = 150


def _preflight() -> None:
    """启动自检：MySQL 与向量库；向量库异常时重建或明确退出，避免演示中途翻车。"""
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
    except Exception as exc:
        print(f"[预检] MySQL 不可用：{exc}")
        print("       请确认 fcr-mysql 容器已启动（docker start fcr-mysql）")
        sys.exit(1)
    print("[预检] MySQL 连接正常")

    try:
        from src.infrastructure.vectorstore import get_vector_store
        from src.utils.config import settings

        store = get_vector_store()
        prefix = settings.app_config("vectorstore").get("collection_prefix", "legal_")
        articles = store.count(prefix + "articles")
        if articles <= 0:
            raise RuntimeError(f"条款向量集合为空（count={articles}）")
        print(f"[预检] 向量库正常（条款向量 {articles} 条）")
    except Exception as exc:
        print(f"[预检] 向量库异常：{exc}")
        if "--reindex" not in sys.argv:
            print("       混合检索将降级、部分审查任务可能失败；请执行：")
            print("       python scripts/demo/run_impact_demo.py --reindex")
            sys.exit(1)
        print("[预检] --reindex：重建条款与罚单向量索引……")
        for script in ("index_articles.py", "index_cases.py"):
            result = subprocess.run(
                [sys.executable, str(Path(__file__).parent.parent / "init_data" / script)],
                check=False,
            )
            if result.returncode != 0:
                print(f"[预检] {script} 重建失败（退出码 {result.returncode}），中止演示")
                sys.exit(1)
        print("[预检] 向量索引重建完成")


def _step(title: str) -> None:
    print(f"\n{'=' * 8} {title} {'=' * 8}")


def _wait_batch_terminal(h: dict, batch_id: int) -> dict:
    """轮询批次到终态；awaiting_review 的任务自动全部确认后续跑。"""
    deadline = time.time() + WAIT_TIMEOUT_SECONDS
    last: dict = {}
    while time.time() < deadline:
        detail = client.get(f"/api/v1/batches/{batch_id}", headers=h).json()["data"]
        last = detail
        resumed = 0
        for task in detail["tasks"]:
            if task["status"] == "awaiting_review":
                client.post(
                    f"/api/v1/tasks/{task['id']}/human-review",
                    headers=h,
                    json={"rejected_indexes": []},
                )
                resumed += 1
        if detail["batch"]["status"] in ("completed", "failed"):
            return last
        if resumed:
            print(f"  人工复核关卡：自动确认 {resumed} 个任务并续跑")
        time.sleep(3)
    return last


def main() -> None:
    _preflight()
    db = SessionLocal()
    ids = seed_demo(db)
    db.close()

    login = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    h = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    _step(f"1/7 影响分析（监管情报 #{ids['regulation_update_id']}）")
    r = client.post(
        "/api/v1/impact/assessments",
        headers=h,
        json={"regulation_update_id": ids["regulation_update_id"]},
    )
    assert r.status_code == 201, r.text
    a = r.json()["data"]
    aid = a["id"]
    for entry in a["items"]["rules"]:
        print(
            f"  命中规则: {entry['rule_name']}（{entry['severity']}，"
            f"{'结构化关联' if entry['matched_by'] == 'link' else '关键词'}）"
        )
    for m in a["items"]["materials"]:
        print(
            f"  材料[{RISK_LABEL[m['risk_level']]}] {m['name']} —— {m['reason']}"
        )
    print(f"  风险分布: 高{a['high_count']} / 中{a['medium_count']} / 低{a['low_count']}")

    _step("2/7 人工确认影响范围")
    r = client.post(f"/api/v1/impact/assessments/{aid}/confirm", headers=h,
                    json={"action": "confirm"})
    assert r.status_code == 200, r.text
    print(f"  已确认；沉淀关键词命中的规则关联 {r.json()['data']['created_links']} 条")

    _step("3/7 一键创建批量复审（默认高/中风险材料）")
    r = client.post(f"/api/v1/impact/assessments/{aid}/batch", headers=h, json={})
    assert r.status_code == 201, r.text
    batch = r.json()["data"]
    print(f"  批次 #{batch['batch_id']}：{batch['total_count']} 份材料进入双引擎复审")

    _step("4/7 等待审查完成（人工复核关卡自动续跑）")
    detail = _wait_batch_terminal(h, batch["batch_id"])
    for task in detail["tasks"]:
        print(f"  任务 #{task['id']} {task['task_name']}: {task['status']}")

    _step("5/7 整改清单（批次终态自动回写）")
    r = client.get(f"/api/v1/impact/assessments/{aid}/remediation", headers=h)
    remediation = r.json()["data"]["items"]
    target = None
    for entry in remediation:
        if entry["task_status"] != "completed":
            mark = "审查失败"
        else:
            mark = "需整改" if entry["requires_remediation"] else "合规"
        print(
            f"  {entry['material_name']}: 违规 {entry['violation_count']} 处 [{mark}]"
            f"（任务 #{entry['task_id']} {entry['task_status']}）"
        )
        if target is None and entry["requires_remediation"]:
            target = entry

    _step("6/7 记录整改决策")
    if target is not None:
        r = client.post(
            f"/api/v1/impact/assessments/{aid}/remediation",
            headers=h,
            json={"task_id": target["task_id"], "decision": "remediate"},
        )
        assert r.status_code == 200, r.text
        print(f"  {target['material_name']} → 整改中（remediate）")

    _step("7/7 规则版本发布（监管驱动规则库更新）")
    rule_id = ids["rule_ids"][0]
    r = client.post(f"/api/v1/rules/{rule_id}/versions", headers=h)
    assert r.status_code == 201, r.text
    draft = r.json()["data"]
    client.put(
        f"/api/v1/rules/{draft['id']}",
        headers=h,
        json={"description": "演示 v2：补充保本话术变体口径"},
    )
    r = client.post(f"/api/v1/rules/{draft['id']}/publish", headers=h)
    assert r.status_code == 200, r.text
    published = r.json()["data"]
    print(
        f"  「{published['rule']['rule_name']}」v{published['rule']['version']} 已发布生效，"
        f"旧版本 {published['superseded_rule_ids']} 自动停用"
    )

    print(
        f"\n演示完成（数据已保留）。打开前端可查看：法规影响中心评估 #{aid}、"
        f"复审批次 #{batch['batch_id']}、产品材料台账、规则库。"
    )


if __name__ == "__main__":
    main()

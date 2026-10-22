"""真实材料首次实战：批量送审 data/real_materials/ 下的公开材料。

设计要点：
- **HTTP 模式**：任务提交给常驻的 fcr-api（localhost:8000），由系统线程池排队执行
  ——脚本只是投递员与统计员，中途退出不影响任务执行（"系统在自己跑"）。
- 来源可溯：按 manifest.json 逐份送审，提交映射落 review_submissions.json（可断点续跑）。
- HIL 关卡：awaiting_review 任务自动确认续跑（与 demo 脚本一致；系统内部对
  自动确认有独立标记，不污染"真实人工采纳率"口径）。
- 产出：review_summary.json —— 每份的状态/违规数/高风险数/token 用量（首次实战战果原始数据）。

用法（仓库根目录，需常驻 API 可达）：
    python scripts/evaluate/run_real_review.py                # 提交 → 等待 → 汇总
    python scripts/evaluate/run_real_review.py --submit-only  # 只提交
    python scripts/evaluate/run_real_review.py --summary-only # 只汇总已提交任务
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")

import httpx  # noqa: E402

BASE = "http://localhost:8000/api/v1"
MAT_DIR = Path(__file__).resolve().parents[2] / "data" / "real_materials"
SUBMISSIONS = MAT_DIR / "review_submissions.json"
SUMMARY = MAT_DIR / "review_summary.json"
WAIT_TIMEOUT_SECONDS = 3600  # 22 份 / 线程池 2 并发，留足余量
POLL_INTERVAL = 30


def _login(client: httpx.Client) -> dict:
    resp = client.post(
        f"{BASE}/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    token = data.get("token") or data.get("access_token")
    if not token:
        raise RuntimeError(f"登录响应无 token 字段: {list(data)}")
    return {"Authorization": f"Bearer {token}"}


def _load_submissions() -> dict:
    if SUBMISSIONS.exists():
        return json.loads(SUBMISSIONS.read_text(encoding="utf-8"))
    return {}


def _save_submissions(subs: dict) -> None:
    SUBMISSIONS.write_text(
        json.dumps(subs, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _submit_one(client: httpx.Client, headers: dict, it: dict, subs: dict) -> int:
    """落文档 + 建任务，写提交记录，返回 task_id。"""
    fname = it["file"]
    text = (MAT_DIR / fname).read_text(encoding="utf-8")
    title = fname.rsplit(".", 1)[0][:60]

    r = client.post(f"{BASE}/documents/text", headers=headers, json={"text": text, "title": title})
    r.raise_for_status()
    doc_id = r.json()["data"]["document_id"]

    r = client.post(
        f"{BASE}/tasks",
        headers=headers,
        json={"document_id": doc_id, "task_name": f"【实战】{title}", "document_type": "宣传材料"},
    )
    r.raise_for_status()
    task_id = r.json()["data"]["task_id"]
    subs[fname] = {"task_id": task_id, "submitted_at": datetime.now().isoformat(timespec="seconds")}
    _save_submissions(subs)
    return task_id


def _await_task(client: httpx.Client, headers: dict, tid: int, timeout_s: int) -> str:
    """等单个任务到终态（含 HIL 自动确认），返回最终状态。

    串行批量必须等一份跑完再投下一份——否则 22 份并发会瞬间打爆网关 RPM
    （2026-10-12 实测 8 并发即耗尽），这也是 llm_concurrency 被设为 1 的原因。
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = client.get(f"{BASE}/tasks/{tid}", headers=headers)
        if r.status_code == 200:
            st = r.json()["data"]["status"]
            if st == "awaiting_review":
                client.post(f"{BASE}/tasks/{tid}/human-review", headers=headers,
                            json={"rejected_indexes": []})
            elif st in ("completed", "failed"):
                return st
        time.sleep(POLL_INTERVAL)
    return "timeout"


def submit_serial(client: httpx.Client, headers: dict, limit: int, task_timeout_s: int) -> None:
    """串行送审：一份跑完再投下一份（夜间批量用）。"""
    manifest = json.loads((MAT_DIR / "manifest.json").read_text(encoding="utf-8"))
    items = [it for it in manifest["items"] if it.get("status") == "ok"]
    subs = _load_submissions()

    pending = [it for it in items if it["file"] not in subs]
    if limit:
        pending = pending[:limit]
    print(f"串行送审：待处理 {len(pending)} 份（已提交 {len(subs)} 份）")

    for n, it in enumerate(pending, 1):
        t0 = time.time()
        tid = _submit_one(client, headers, it, subs)
        print(f"  [{n}/{len(pending)}] 已提交 #{tid}: {it['file'][:36]}", flush=True)
        st = _await_task(client, headers, tid, task_timeout_s)
        print(f"      → {st}，用时 {round(time.time() - t0)}s", flush=True)


def submit(client: httpx.Client, headers: dict) -> None:
    """逐份送审（幂等：已提交的跳过）。"""
    manifest = json.loads((MAT_DIR / "manifest.json").read_text(encoding="utf-8"))
    items = [it for it in manifest["items"] if it.get("status") == "ok"]
    subs = _load_submissions()

    new = 0
    for it in items:
        fname = it["file"]
        if fname in subs:
            print(f"  跳过（已提交）: {fname}")
            continue
        text = (MAT_DIR / fname).read_text(encoding="utf-8")
        title = fname.rsplit(".", 1)[0][:60]

        # 1) 落成文档
        r = client.post(
            f"{BASE}/documents/text", headers=headers, json={"text": text, "title": title}
        )
        r.raise_for_status()
        doc_id = r.json()["data"]["document_id"]

        # 2) 创建审查任务（domain 留空：由系统自动识别——顺带检验 classify 能力）
        r = client.post(
            f"{BASE}/tasks",
            headers=headers,
            json={
                "document_id": doc_id,
                "task_name": f"【实战】{title}",
                "document_type": "宣传材料",
            },
        )
        r.raise_for_status()
        task_id = r.json()["data"]["task_id"]
        subs[fname] = {
            "task_id": task_id,
            "submitted_at": datetime.now().isoformat(timespec="seconds"),
        }
        _save_submissions(subs)
        new += 1
        print(f"  已提交 #{task_id}: {fname}")

    print(f"提交完成：新增 {new} / 跳过 {len(items) - new} / 共 {len(subs)}")


def summarize(client: httpx.Client, headers: dict, wait: bool) -> None:
    """轮询至终态（可选）并汇总统计。"""
    subs = _load_submissions()
    if not subs:
        raise SystemExit("无提交记录，先运行提交或去掉 --summary-only")

    tasks = {fname: rec["task_id"] for fname, rec in subs.items()}
    deadline = time.time() + WAIT_TIMEOUT_SECONDS

    while wait:
        done = failed = awaiting = running = 0
        for tid in tasks.values():
            r = client.get(f"{BASE}/tasks/{tid}", headers=headers)
            if r.status_code != 200:
                continue
            st = r.json()["data"]["status"]
            if st == "awaiting_review":
                client.post(
                    f"{BASE}/tasks/{tid}/human-review",
                    headers=headers,
                    json={"rejected_indexes": []},
                )
                awaiting += 1
            elif st == "completed":
                done += 1
            elif st == "failed":
                failed += 1
            else:
                running += 1
        remaining = len(tasks) - done - failed
        print(
            f"  [{datetime.now():%H:%M:%S}] 完成 {done} / 失败 {failed} / "
            f"进行中 {running} / 待复核 {awaiting}"
        )
        if remaining == 0:
            wait = False
            break
        if time.time() > deadline:
            print("  等待超时，汇总当前状态")
            break
        time.sleep(POLL_INTERVAL)

    # 汇总
    items_out: list[dict] = []
    total_v = total_high = total_tokens = 0
    for fname, tid in tasks.items():
        rec: dict = {"file": fname, "task_id": tid}
        r = client.get(f"{BASE}/tasks/{tid}", headers=headers)
        detail = r.json()["data"] if r.status_code == 200 else {}
        rec["status"] = detail.get("status")
        rec["domain"] = detail.get("domain")
        rec["stages"] = len(detail.get("stages") or {})
        if detail.get("status") == "completed":
            rr = client.get(f"{BASE}/tasks/{tid}/report", headers=headers)
            if rr.status_code == 200:
                rep = rr.json()["data"]
                summary = rep.get("summary") or {}
                usage = rep.get("llm_usage") or {}
                rec["violations"] = summary.get("total_violations")
                rec["high_risk"] = summary.get("high_risk")
                rec["pending_verification"] = len(rep.get("pending_verification") or [])
                rec["tokens"] = usage.get("total_tokens")
                total_v += summary.get("total_violations") or 0
                total_high += summary.get("high_risk") or 0
                total_tokens += usage.get("total_tokens") or 0
        items_out.append(rec)

    out = {
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "total": len(items_out),
        "completed": sum(1 for i in items_out if i["status"] == "completed"),
        "failed": sum(1 for i in items_out if i["status"] == "failed"),
        "totals": {
            "violations": total_v,
            "high_risk": total_high,
            "tokens": total_tokens,
        },
        "items": items_out,
    }
    SUMMARY.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"\n首战汇总：{out['completed']}/{out['total']} 完成，"
        f"违规 {total_v} 条（高危 {total_high}），token {total_tokens:,} → {SUMMARY}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--submit-only", action="store_true")
    ap.add_argument("--summary-only", action="store_true")
    ap.add_argument(
        "--serial",
        action="store_true",
        help="串行送审：一份跑完再投下一份（夜间批量/避免打爆网关 RPM）",
    )
    ap.add_argument("--limit", type=int, default=0, help="串行模式下最多处理几份（0=全部）")
    ap.add_argument(
        "--task-timeout",
        type=int,
        default=1800,
        help="单份最长等待秒数（超时则跳过继续下一份）",
    )
    args = ap.parse_args()

    with httpx.Client(timeout=60) as client:
        headers = _login(client)
        print("登录成功")
        if args.serial:
            submit_serial(client, headers, args.limit, args.task_timeout)
            summarize(client, headers, wait=False)
            return
        if not args.summary_only:
            submit(client, headers)
        if not args.submit_only:
            summarize(client, headers, wait=not args.summary_only)


if __name__ == "__main__":
    main()

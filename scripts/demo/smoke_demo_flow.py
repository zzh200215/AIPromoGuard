"""八步演示动线冒烟（部署验收）：

    1. 登录      POST /auth/login（admin）
    2. 上传      POST /documents/upload（multipart，演示材料含明确违规表述）
    3. 审查      POST /tasks → 轮询至 completed → 结论至少 1 条
    4. 人工复核  POST /results/bulk-confirm（待复核清零）
    5. 签发      POST /tasks/{id}/sign-off（released）+ GET 复核结论
    6. 证据包    GET /tasks/{id}/evidence-pack → zip 内 manifest SHA256/字节数逐文件校验
    7. 影响中心  GET /impact/overview（关键字段齐全）
    8. 整改闭环  停用规则(制造依据失效) → 建材料 → stale 同步命中 → 决策需整改
                 → 上传整改版(升版 v2) → 复测通过自动关闭 → 复原（规则启用/材料归档）

用法（项目根执行）：
    python scripts/demo/smoke_demo_flow.py
    STAGING_API_BASE=http://127.0.0.1:8000 python scripts/demo/smoke_demo_flow.py   # 打本机 dev

设计约定：
- 幂等可重复：每次运行新建文档/任务/材料（名称带时间戳），不依赖前次状态；
  结束时复原环境（规则重新启用、材料归档）——失败也会尽力复原（finally）。
- 任一步失败：打印失败步与响应体片段，退出码 1（CI/部署验收直接判红）。
- 本脚本是后续所有 PR 的部署验收步骤（合入 staging 后必跑）。

环境变量可覆盖：
    STAGING_API_BASE       默认 http://127.0.0.1:8001
    STAGING_ADMIN_PASSWORD 默认 admin123
    SMOKE_REVIEW_TIMEOUT   审查等待上限秒数，默认 300
    SMOKE_RETEST_TIMEOUT   复测自动关闭等待上限秒数，默认 240
"""

import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import datetime

API = os.environ.get("STAGING_API_BASE", "http://127.0.0.1:8001").rstrip("/")
ADMIN_PASSWORD = os.environ.get("STAGING_ADMIN_PASSWORD", "admin123")
REVIEW_TIMEOUT = int(os.environ.get("SMOKE_REVIEW_TIMEOUT", "300"))
RETEST_TIMEOUT = int(os.environ.get("SMOKE_RETEST_TIMEOUT", "240"))

STAMP = datetime.now().strftime("%Y%m%d%H%M%S")

# 注意：材料**正文里不放长数字串**（运行标记只出现在文件名）——
# 13~19 位连续数字且恰好通过 Luhn 校验就会被 PII 内置检查判为"疑似银行卡号"
# （2026-10-08 实测：14 位时间戳 20261008190831 偶合 Luhn 触发了该判定）。
# 演示材料：刻意含明确违规表述（保本保息/稳赚不赔/预期年化收益），
# 保证复核、签发、证据包各步都有真实结论可走
DEMO_MATERIAL = (
    "稳健回报混合型基金 产品宣传单页（演示动线）\n"
    "本产品保本保息，稳赚不赔，预期年化收益 12%，限时抢购，扫码立即申购。\n"
    "风险提示：投资有风险，入市需谨慎。"
)
# 整改版：规范表述（开发环境已预检：规则零命中 + 真实管线零违规），
# 保证复测走"通过 → 自动关闭"路径
RETEST_MATERIAL = (
    "稳健回报混合型基金 产品资料更新说明（演示动线整改版）\n"
    "本基金为混合型证券投资基金，属于中风险等级产品。\n"
    "投资者在投资本基金前应认真阅读基金合同、招募说明书等法律文件，"
    "了解本基金的风险收益特征，并根据自身风险承受能力谨慎作出投资决策。\n"
    "基金管理人依照恪尽职守、诚实信用、谨慎勤勉的原则管理和运用基金资产，"
    "但不保证基金一定盈利。\n"
    "本材料已按照现行有效的法律法规及监管要求完成核对更新。"
)

# 绕过系统代理：staging 在本机回环地址，走代理会得到 502 而非真实结果
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class StepError(Exception):
    """冒烟断言失败：携带失败步与响应体片段（部署验收直接判红）。"""

    def __init__(self, step: str, detail: str):
        super().__init__(f"[{step}] {detail}")
        self.step = step
        self.detail = detail


def _http(url: str, method: str = "GET", data: bytes | None = None,
          headers: dict | None = None, timeout: int = 60) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        return 0, f"连接失败: {e.reason}".encode()


def _multipart(fields: dict[str, str],
               files: list[tuple[str, str, bytes]]) -> tuple[bytes, str]:
    """stdlib multipart/form-data 编码（上传文档与整改版两处用）。"""
    boundary = "----smoke" + uuid.uuid4().hex
    out = bytearray()
    for name, value in fields.items():
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += value.encode("utf-8") + b"\r\n"
    for name, filename, content in files:
        out += f"--{boundary}\r\n".encode()
        out += (
            f'Content-Disposition: form-data; name="{name}"; '
            f'filename="{filename}"\r\n'
        ).encode()
        out += b"Content-Type: application/octet-stream\r\n\r\n"
        out += content + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def _snippet(raw: bytes, limit: int = 300) -> str:
    """响应体转可读片段（失败信息里直接展示，便于定位）。"""
    return raw[:limit].decode("utf-8", "replace")


def _call(step: str, method: str, path: str, *, body: dict | None = None,
          token: str | None = None, expect: tuple = (200,), timeout: int = 60,
          raw_data: bytes | None = None, content_type: str | None = None,
          soft: bool = False) -> dict:
    """调用业务 API 并断言 code=0，返回 data。soft=True 用于清理阶段吞错。"""
    headers: dict[str, str] = {}
    data: bytes | None = None
    if raw_data is not None:
        data = raw_data
        headers["Content-Type"] = content_type or "application/octet-stream"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    status, raw = _http(f"{API}/api/v1{path}", method, data, headers, timeout)
    if soft and status not in expect:
        print(f"  ! 清理动作未成功（{method} {path} → HTTP {status}），请人工确认")
        return {}
    if status not in expect:
        raise StepError(step, f"{method} {path} → HTTP {status}: {_snippet(raw)}")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise StepError(
            step, f"{method} {path} → 非 JSON 响应: {_snippet(raw, 200)}"
        ) from None
    if payload.get("code") != 0:
        raise StepError(step, f"{method} {path} → 业务错误: {_snippet(raw)}")
    return payload.get("data") or {}


def _get_bytes(step: str, path: str, token: str, timeout: int = 120) -> tuple[int, bytes]:
    status, raw = _http(
        f"{API}/api/v1{path}", "GET",
        headers={"Authorization": f"Bearer {token}"}, timeout=timeout,
    )
    if status != 200:
        raise StepError(step, f"GET {path} → HTTP {status}: {_snippet(raw, 200)}")
    return status, raw


# ---------- 八步 ----------


def step1_login() -> str:
    data = _call("1 登录", "POST", "/auth/login",
                 body={"username": "admin", "password": ADMIN_PASSWORD})
    token = data.get("access_token")
    if not token:
        raise StepError("1 登录", "响应缺少 access_token")
    print("✓ [1/8] 登录（admin）")
    return token


def step2_upload(token: str) -> str:
    content = DEMO_MATERIAL.encode("utf-8")
    body, ctype = _multipart({}, [("file", f"演示动线材料_{STAMP}.txt", content)])
    data = _call("2 上传", "POST", "/documents/upload", token=token,
                 raw_data=body, content_type=ctype, expect=(201,))
    doc_id = data.get("document_id")
    if not doc_id:
        raise StepError("2 上传", f"响应缺少 document_id: {data}")
    print(f"✓ [2/8] 上传演示材料（{doc_id}，{len(content)} 字节）")
    return doc_id


def step3_review(token: str, doc_id: str) -> tuple[int, list[dict]]:
    data = _call("3 审查", "POST", "/tasks", token=token,
                 body={"document_id": doc_id, "task_name": f"演示动线-{STAMP}",
                       "document_type": "宣传材料"}, expect=(201,))
    task_id = data.get("task_id")
    if not task_id:
        raise StepError("3 审查", f"响应缺少 task_id: {data}")

    deadline = time.time() + REVIEW_TIMEOUT
    resumed = False
    while True:
        if time.time() > deadline:
            raise StepError("3 审查", f"等待审查完成超时（{REVIEW_TIMEOUT}s），task={task_id}")
        task = _call("3 审查", "GET", f"/tasks/{task_id}", token=token)
        status = task.get("status")
        if status == "awaiting_review":
            # 工作流启用人工复核闸门时：空决策恢复（否决集为空）后继续
            if not resumed:
                _call("3 审查", "POST", f"/tasks/{task_id}/human-review",
                      body={"rejected_indexes": []}, token=token)
                resumed = True
        elif status == "completed":
            break
        elif status in ("failed", "cancelled"):
            raise StepError("3 审查", f"任务终态异常: {status}（task={task_id}）")
        time.sleep(3)

    results = _call("3 审查", "GET", f"/tasks/{task_id}/results", token=token)
    items = results.get("items") or []
    if not items:
        raise StepError("3 审查", "未检出任何结论（演示材料应含明确违规表述）")
    print(f"✓ [3/8] 审查完成（task={task_id}，结论 {len(items)} 条）")
    return task_id, items


def step4_human_review(token: str, task_id: int, items: list[dict]) -> list[dict]:
    pending = [r["result_id"] for r in items if r.get("status") == "pending_confirm"]
    if pending:
        _call("4 复核", "POST", "/results/bulk-confirm", token=token,
              body={"result_ids": pending, "verdict": "confirmed",
                    "note": "演示动线冒烟：批量确认"})
    after = _call("4 复核", "GET", f"/tasks/{task_id}/results", token=token)
    rows = after.get("items") or []
    left = [r for r in rows if r.get("status") == "pending_confirm"]
    if left:
        raise StepError("4 复核", f"仍有 {len(left)} 条待复核未清零")
    auto = sum(1 for r in rows if r.get("auto_confirmed"))
    print(f"✓ [4/8] 人工复核完成（本次确认 {len(pending)} 条，自动确认 {auto} 条）")
    return rows


def step5_sign_off(token: str, task_id: int) -> None:
    _call("5 签发", "POST", f"/tasks/{task_id}/sign-off", token=token,
          body={"decision": "released", "note": "演示动线冒烟：放行"})
    rec = _call("5 签发", "GET", f"/tasks/{task_id}/sign-off", token=token)
    if not rec or rec.get("decision") != "released":
        raise StepError("5 签发", f"签发结论异常: {rec}")
    print(f"✓ [5/8] 审核签发（released，by {rec.get('username')}）")


def step6_evidence_pack(token: str, task_id: int) -> None:
    _, raw = _get_bytes("6 证据包", f"/tasks/{task_id}/evidence-pack", token)
    if raw[:2] != b"PK":
        raise StepError("6 证据包", "响应不是 zip（PK 魔数缺失）")
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = set(zf.namelist())
        need = {"manifest.json", "审查报告.md", "审查报告.json",
                "结论生命周期.csv", "操作留痕.csv"}
        missing = sorted(need - names)
        if missing:
            raise StepError("6 证据包", f"包内缺文件: {missing}")
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        if (manifest.get("task") or {}).get("task_id") != task_id:
            raise StepError("6 证据包", f"manifest.task.task_id 不匹配: {manifest.get('task')}")
        for name, meta in (manifest.get("files") or {}).items():
            blob = zf.read(name)
            if hashlib.sha256(blob).hexdigest() != meta.get("sha256"):
                raise StepError("6 证据包", f"{name} SHA256 与 manifest 不一致")
            if len(blob) != meta.get("bytes"):
                raise StepError("6 证据包", f"{name} 字节数与 manifest 不一致")
    print(f"✓ [6/8] 证据包下载 + manifest 校验（{len(manifest['files'])} 文件 SHA256/字节数全对）")


def step7_impact_overview(token: str) -> dict:
    data = _call("7 影响中心", "GET", "/impact/overview", token=token)
    need = ("remediation_total", "stale_materials", "patrol_counts", "high_risk_materials")
    missing = [k for k in need if k not in data]
    if missing:
        raise StepError("7 影响中心", f"概览缺字段: {missing}")
    stale_count = (data.get("stale_materials") or {}).get("stale_count")
    print(f"✓ [7/8] 影响中心概览（待整改 {data.get('remediation_total')} 条，"
          f"依据失效 {stale_count} 条）")
    return data


def step8_remediation_loop(token: str, doc_id: str, items: list[dict]) -> None:
    """整改闭环：制造依据失效 → 同步命中 → 决策 → 升版复测 → 自动关闭 → 复原。"""
    step = "8 整改闭环"
    rule_id = next((r.get("rule_id") for r in items if r.get("rule_id")), None)
    if rule_id is None:
        raise StepError(step, "本任务无规则命中（rule_id 缺失），无法构造依据失效链")

    # a) 停用本任务命中的规则 → 该材料"依据失效"
    _call(step, "PUT", f"/rules/{rule_id}", token=token, body={"is_active": False})
    print(f"  · 已停用规则 #{rule_id}（制造依据失效；演示结束后恢复）")

    material_id: int | None = None
    assessment_id: int | None = None
    try:
        # b) 材料台账登记（关联本次演示文档）
        mat = _call(step, "POST", "/impact/materials", token=token, expect=(201,), body={
            "name": f"演示动线材料_{STAMP}", "product_type": "fund",
            "material_type": "单页", "document_id": doc_id,
            "version": "v1", "owner": "冒烟脚本",
        })
        material_id = mat.get("id")
        if not material_id:
            raise StepError(step, f"材料创建响应异常: {mat}")

        # c) 依据失效同步 → 新条目应进入整改清单并被高亮
        sync = _call(step, "POST", "/impact/materials/stale/sync", token=token)
        assessment_id = sync.get("assessment_id")
        if material_id not in (sync.get("highlight_ids") or []):
            raise StepError(
                step,
                f"同步未命中新材料（material={material_id}，"
                f"highlight_ids={sync.get('highlight_ids')}）",
            )
        print(f"  · 依据失效命中：材料 #{material_id} 进入整改清单（评估 #{assessment_id}）")

        # d) 人工决策"需整改"
        _call(step, "POST", f"/impact/assessments/{assessment_id}/remediation",
              token=token, body={"material_id": material_id, "decision": "remediate"})

        # e) 上传整改版 → 升版 v2 并启动复测
        body, ctype = _multipart(
            {"assessment_id": str(assessment_id)},
            [("file", f"整改版_{STAMP}.txt", RETEST_MATERIAL.encode("utf-8"))],
        )
        retest = _call(step, "POST", f"/impact/materials/{material_id}/retest",
                       token=token, raw_data=body, content_type=ctype,
                       expect=(201,), timeout=120)
        if retest.get("version") != "v2":
            raise StepError(step, f"未升版 v2: {retest}")

        # f) 轮询复测结果：通过 → 原整改项自动关闭
        deadline = time.time() + RETEST_TIMEOUT
        entry: dict | None = None
        rem: dict = {}
        while True:
            if time.time() > deadline:
                retest_entry = next(
                    (e for e in (rem.get("items") or [])
                     if e.get("retest") and e.get("material_id") == material_id),
                    None,
                )
                raise StepError(
                    step,
                    f"等待复测自动关闭超时（{RETEST_TIMEOUT}s）；原条目 decision="
                    f"{entry.get('decision') if entry else None}，"
                    f"复测条目={retest_entry}（violation_count>0 表示整改版仍违规）",
                )
            rem = _call(step, "GET", f"/impact/assessments/{assessment_id}/remediation",
                        token=token)
            entry = next(
                (e for e in rem.get("items") or []
                 if e.get("kind") == "stale" and e.get("material_id") == material_id),
                None,
            )
            if entry and entry.get("decision") == "done":
                break
            time.sleep(5)
        print(f"✓ [8/8] 整改闭环（升版 {retest.get('version')} → 复测任务 "
              f"#{retest.get('task_id')} → 原整改项自动关闭）")
    finally:
        # g) 复原环境（无论成败，尽力而为）：规则重新启用、材料归档
        _call(step, "PUT", f"/rules/{rule_id}", token=token,
              body={"is_active": True}, soft=True)
        if material_id is not None:
            _call(step, "PATCH", f"/impact/materials/{material_id}", token=token,
                  body={"status": "archived"}, soft=True)
        print("  · 环境复原：规则已重新启用、材料已归档")


def main() -> None:
    started = time.time()
    print(f"八步演示动线冒烟：API={API}（运行标记 {STAMP}）")
    token = step1_login()
    doc_id = step2_upload(token)
    task_id, items = step3_review(token, doc_id)
    step4_human_review(token, task_id, items)
    step5_sign_off(token, task_id)
    step6_evidence_pack(token, task_id)
    step7_impact_overview(token)
    step8_remediation_loop(token, doc_id, items)
    elapsed = time.time() - started
    print(f"PASS：八步演示动线全通过（{elapsed:.0f}s）")


if __name__ == "__main__":
    try:
        main()
    except StepError as exc:
        print(f"✗ {exc}")
        sys.exit(1)

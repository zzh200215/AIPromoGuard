"""staging 冒烟：四断言（任一失败即红，退出码 1）。

用法（项目根执行；staging 已由 scripts/deploy/init_staging.py 初始化）：
    python scripts/demo/smoke_staging.py

断言：
    1. 后端健康   GET  {API}/api/v1/health                     → 200
    2. 登录       POST {API}/api/v1/auth/login (admin/密码)     → code=0 且取到 access_token
    3. 任务列表   GET  {API}/api/v1/tasks   (Bearer)            → 200
    4. 前端页面   GET  {WEB}/                                    → 200 且为 SPA index.html
       + 反代链路 GET  {WEB}/api/v1/health                       → 200（前端页面调 API 的实际路径）

环境变量可覆盖：
    STAGING_API_BASE（默认 http://127.0.0.1:8001）
    STAGING_WEB_BASE（默认 http://127.0.0.1:8081）
    STAGING_ADMIN_PASSWORD（默认 admin123）
"""

import json
import os
import sys
import urllib.error
import urllib.request

API = os.environ.get("STAGING_API_BASE", "http://127.0.0.1:8001")
WEB = os.environ.get("STAGING_WEB_BASE", "http://127.0.0.1:8081")
ADMIN_PASSWORD = os.environ.get("STAGING_ADMIN_PASSWORD", "admin123")

# 绕过系统代理：staging 在本机回环地址，走代理会得到 502 而非真实结果
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _request(url: str, method: str = "GET", body: dict | None = None,
             token: str | None = None, timeout: int = 15):
    """返回 (status_code, text)；HTTP 错误也返回响应体（断言友好）。"""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        # 连接级失败（服务未启动/端口不通）：返回 0 由断言函数友好报错
        return 0, f"连接失败: {e.reason}"


def _fail(step: str, detail: str) -> None:
    print(f"✗ [{step}] {detail}")
    sys.exit(1)


def assert_health() -> None:
    status, text = _request(f"{API}/api/v1/health")
    if status != 200:
        _fail("健康检查", f"HTTP {status}: {text[:200]}")
    print("✓ [1/4] 后端健康")


def assert_login() -> str:
    status, text = _request(f"{API}/api/v1/auth/login", "POST",
                            {"username": "admin", "password": ADMIN_PASSWORD})
    if status != 200:
        _fail("登录", f"HTTP {status}: {text[:200]}")
    payload = json.loads(text)
    token = (payload.get("data") or {}).get("access_token")
    if payload.get("code") != 0 or not token:
        _fail("登录", f"响应异常: {text[:200]}")
    print("✓ [2/4] 登录（admin）")
    return token


def assert_tasks(token: str) -> None:
    status, text = _request(f"{API}/api/v1/tasks", token=token)
    if status != 200:
        _fail("任务列表", f"HTTP {status}: {text[:200]}")
    print("✓ [3/4] 任务列表")


def assert_web() -> None:
    status, text = _request(f"{WEB}/")
    if status != 200 or 'id="app"' not in text:
        _fail("前端页面", f"HTTP {status}，非预期 index.html: {text[:120]}")
    # nginx 反代链路：前端页面调用 API 走的就是这条路径
    status, text = _request(f"{WEB}/api/v1/health")
    if status != 200:
        _fail("前端反代", f"HTTP {status}: {text[:200]}")
    print("✓ [4/4] 前端页面 + API 反代")


def main() -> None:
    print(f"staging 冒烟：API={API} WEB={WEB}")
    assert_health()
    token = assert_login()
    assert_tasks(token)
    assert_web()
    print("PASS：staging 四断言全过")


if __name__ == "__main__":
    main()

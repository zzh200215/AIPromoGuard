"""locust 压测脚本（PRD §14 性能测试 / Phase 4 验收：并发 10/50/100、单文档端到端 ≤5 分钟）。

每个虚拟用户：登录一次 → 上传样本 → 循环「建任务 → 轮询完成」，端到端耗时作为
自定义指标 e2e_review 计入 locust 统计（含并发排队时间，反映线程池真实吞吐）。

用法:
    locust -f scripts/benchmark/locustfile.py --host http://localhost:8000
    locust -f scripts/benchmark/locustfile.py --headless -u 10 -r 2 -t 3m \
           --host http://localhost:8000

环境变量（可选）:
    LOCUST_USERNAME / LOCUST_PASSWORD   登录账号（默认 admin / admin123）
    LOCUST_POLL_TIMEOUT                 单任务轮询超时秒数（默认 180）
"""

import os
import time
from pathlib import Path

from locust import HttpUser, between, events, task

API = "/api/v1"
USERNAME = os.getenv("LOCUST_USERNAME", "admin")
PASSWORD = os.getenv("LOCUST_PASSWORD", "admin123")
POLL_TIMEOUT = int(os.getenv("LOCUST_POLL_TIMEOUT", "180"))
SAMPLE = Path(__file__).with_name("sample.txt")


def _data(resp):
    """解包统一响应 envelope {code,message,data}。"""
    return resp.json().get("data")


class ReviewUser(HttpUser):
    """审查用户：登录 → 上传 → 建任务并轮询至完成。"""
    wait_time = between(0.5, 1.5)

    def on_start(self):
        resp = self.client.post(f"{API}/auth/login",
                                json={"username": USERNAME, "password": PASSWORD},
                                name="auth/login")
        if resp.status_code != 200:
            raise RuntimeError(f"登录失败: {resp.status_code} {resp.text[:200]}")
        self.token = _data(resp)["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

        with open(SAMPLE, "rb") as f:
            resp = self.client.post(f"{API}/documents/upload",
                                    files={"file": (SAMPLE.name, f, "text/plain")},
                                    headers=self.headers,
                                    name="documents/upload")
            self.document_id = _data(resp)["document_id"]

    @task(4)
    def create_and_wait_review(self):
        """建任务 → 轮询到 completed/failed（端到端含排队），耗时计入 e2e_review。"""
        start = time.perf_counter()
        try:
            resp = self.client.post(f"{API}/tasks",
                                    json={"document_id": self.document_id, "document_type": "txt"},
                                    headers=self.headers,
                                    name="tasks/create")
            if resp.status_code != 201:
                raise RuntimeError(f"建任务失败: {resp.status_code} {resp.text[:200]}")
            task_id = _data(resp)["task_id"]

            elapsed = _poll_task(self, task_id)
        except Exception as exc:  # noqa: BLE001
            elapsed = int((time.perf_counter() - start) * 1000)
            events.request.fire(request_type="TASK", name="e2e_review", response_time=elapsed,
                                response_length=0, exception=exc)
            return

        events.request.fire(request_type="TASK", name="e2e_review", response_time=elapsed,
                            response_length=0, exception=None)

    @task(1)
    def list_tasks(self):
        """轻量接口：并发下的 API 响应性。"""
        self.client.get(f"{API}/tasks", headers=self.headers, name="tasks/list")


def _poll_task(user: HttpUser, task_id: int) -> int:
    """轮询任务直至完成/失败，返回端到端毫秒数（含排队等待）。"""
    start = time.perf_counter()
    while time.perf_counter() - start < POLL_TIMEOUT:
        resp = user.client.get(f"{API}/tasks/{task_id}", headers=user.headers, name="tasks/status")
        status = _data(resp)["status"]
        if status in ("completed", "failed", "cancelled"):
            return int((time.perf_counter() - start) * 1000)
        time.sleep(0.5)
    raise TimeoutError(f"task {task_id} 轮询超时（{POLL_TIMEOUT}s），status={status}")

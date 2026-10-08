"""staging 环境幂等初始化：镜像检查 → chroma 快照 → 起栈 → 种子 → 就绪提示。

用法（项目根执行）：
    python scripts/deploy/init_staging.py                  # 完整初始化（幂等，可反复跑）
    python scripts/deploy/init_staging.py --skip-seed      # 只起栈（库已有数据时）
    python scripts/deploy/init_staging.py --refresh-chroma # 强制用主数据目录刷新 chroma 快照

步骤：
    1. 镜像检查：financial-compliance-review-api / -web 缺失则报错并给出构建指引
       （不在本脚本构建——中文路径 buildx bug，见 docker/docker-compose.yml 顶部注释）
    2. chroma 快照：data/chroma → data_staging/chroma（目标已存在则跳过；
       栈运行中刷新后自动 restart staging-api 重新加载）
    3. docker compose -f docker/docker-compose.staging.yml up -d（api 容器启动时自动 alembic 迁移）
    4. 等待 staging-api 健康
    5. 种子（docker exec 在容器内执行，环境与运行时完全一致）：
       规则 ×2 → 法规 ×3 → 罚单 → RBAC/管理员 → 条款/案例向量索引

完成后：python scripts/demo/smoke_staging.py（四断言冒烟）
"""

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "docker" / "docker-compose.staging.yml"

API_IMAGE = "financial-compliance-review-api"
WEB_IMAGE = "financial-compliance-review-web"

SEED_COMMANDS = [
    ["python", "scripts/init_data/import_rules.py"],
    ["python", "scripts/init_data/import_rules.py", "--json", "scripts/init_data/rules_mined.json"],
    ["python", "scripts/init_data/import_regulations.py"],
    ["python", "scripts/init_data/import_regulations.py", "--json",
     "scripts/init_data/regulations_core_extra.json"],
    ["python", "scripts/init_data/import_regulations.py", "--json",
     "scripts/init_data/regulations_crawled.json"],
    ["python", "scripts/init_data/import_penalty_cases.py"],
    ["python", "scripts/init_data/init_admin.py"],
    ["python", "scripts/init_data/index_articles.py"],
    ["python", "scripts/init_data/index_cases.py"],
]

BUILD_HINT = f"""\
  构建指引（ASCII 路径 workaround，Git Bash 执行；见 docker/docker-compose.yml 顶部注释）：
    rm -rf /tmp/fcr-build && mkdir -p /tmp/fcr-build
    cp -r docker requirements.txt pyproject.toml alembic.ini \\
       src configs scripts migrations models_cache /tmp/fcr-build/
    (cd frontend && tar cf - --exclude=node_modules --exclude=dist .) \\
       | (mkdir -p /tmp/fcr-build/frontend && cd /tmp/fcr-build/frontend && tar xf -)
    (cd data/models/fastembed && tar cf - --exclude=.locks .) \\
       | (cd /tmp/fcr-build/models_cache && tar xf -)
    cd /tmp/fcr-build
    docker build -f docker/Dockerfile.api -t {API_IMAGE} .
    docker build -f docker/Dockerfile.frontend -t {WEB_IMAGE} .
  （末两步模型缓存复制为离线构建路径，见 models_cache/README.md；跳过则走在线下载）
"""


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=ROOT, text=True, **kw)


def check_images() -> None:
    print("[1/5] 镜像检查")
    r = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}"], capture_output=True, text=True
    )
    have = set(r.stdout.split())
    missing = [img for img in (API_IMAGE, WEB_IMAGE) if img not in have]
    if missing:
        print(f"  ✗ 缺少镜像: {', '.join(missing)}")
        print(BUILD_HINT)
        sys.exit(1)
    print("  ✓ api / web 镜像齐备")


def snapshot_chroma(refresh: bool) -> None:
    print("[2/5] chroma 快照（data/chroma → data_staging/chroma）")
    src, dst = ROOT / "data" / "chroma", ROOT / "data_staging" / "chroma"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and not refresh:
        print("  ✓ 已存在，跳过（--refresh-chroma 可强制刷新）")
        return
    if not src.exists():
        print(f"  ✗ 主数据目录缺少 {src}（先对主库跑 index_articles/index_cases）")
        sys.exit(1)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    print(f"  ✓ 已复制 {src} → {dst}")


def compose_up() -> None:
    print("[3/5] 起栈（compose up -d，幂等）")
    r = run(["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d"])
    if r.returncode != 0:
        # 首次启动竞态：mysql 初始化期间 health 探针可能误报就绪，api 连接被拒后
        # 由 restart 策略自愈（表现为 compose 等待依赖失败而返回非零）。
        # 不立即退出——交由 wait_health 以更长超时兜底判定。
        print("  ! compose 返回非零（首次启动竞态常见，容器将自愈）——继续等待健康")


def wait_health(timeout_s: int = 180) -> None:
    print(f"[4/5] 等待 staging-api 健康（≤{timeout_s}s）")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", "staging-api"],
            capture_output=True, text=True,
        )
        if r.stdout.strip() == "healthy":
            print("  ✓ healthy")
            return
        time.sleep(3)
    print("  ✗ 超时：docker logs staging-api 查看原因")
    sys.exit(1)


def seed() -> None:
    print("[5/5] 种子（容器内执行，全部幂等）")
    for cmd in SEED_COMMANDS:
        r = run(["docker", "exec", "staging-api", *cmd])
        if r.returncode != 0:
            print(f"  ✗ 失败: {' '.join(cmd)}")
            sys.exit(1)
    print("  ✓ 种子完成")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-seed", action="store_true", help="跳过种子（库已有数据）")
    parser.add_argument("--refresh-chroma", action="store_true", help="强制刷新 chroma 快照")
    args = parser.parse_args()

    check_images()
    snapshot_chroma(refresh=args.refresh_chroma)
    compose_up()
    wait_health()
    if args.skip_seed:
        print("[5/5] 跳过种子（--skip-seed）")
        # 注意：跳过种子但刷新过 chroma 时，确保 api 重新加载
        if args.refresh_chroma:
            run(["docker", "compose", "-f", str(COMPOSE_FILE), "restart", "staging-api"])
    else:
        seed()
        if args.refresh_chroma:
            run(["docker", "compose", "-f", str(COMPOSE_FILE), "restart", "staging-api"])

    print()
    print("staging 就绪：")
    print("  API  http://localhost:8001/api/v1/health")
    print("  前端 http://localhost:8081")
    print("  冒烟 python scripts/demo/smoke_staging.py")


if __name__ == "__main__":
    main()

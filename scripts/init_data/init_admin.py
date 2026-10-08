"""初始化 RBAC 基础数据：角色权限 + admin 账号。

用法:
    python scripts/init_data/init_admin.py [password]
默认密码 admin123（生产环境务必修改）。

说明（2026-10-08 PR-0a）：
- 角色权限是 RBAC 的代码侧定义——权限中间件（src/api/middleware/auth.py）
  按 roles 表的 JSON 权限校验，**roles 表为空时所有需权限的接口全 403**。
  此前该种子藏在 docker/init-scripts/init_mysql.sql 里（随 init SQL 下线一并
  迁移至此），新库（Alembic 建库）与 CI 必须执行本脚本。
- 幂等：角色缺失则插入，已存在则同步为下方定义（与 admin 密码重置同一哲学：
  以代码/发布为准收敛，手工改库会被下一次执行覆盖）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.infrastructure.database.mysql import SessionLocal
from src.models import Role, User
from src.utils.security import hash_password

# 权限矩阵（对齐 PRD §13.1；与历史 init_mysql.sql 的默认数据一致）
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "admin": [
        "upload",
        "create_task",
        "view_report",
        "confirm",
        "manage_regulations",
        "manage_rules",
        "manage_users",
        "monitor",
    ],
    "reviewer": ["upload", "create_task", "view_report", "confirm"],
    "viewer": ["view_report"],
}


def ensure_roles(db) -> int:
    """幂等同步角色权限；返回新建角色数。"""
    created = 0
    for name, permissions in ROLE_PERMISSIONS.items():
        role = db.query(Role).filter(Role.name == name).first()
        if role is None:
            db.add(Role(name=name, permissions=list(permissions)))
            created += 1
        else:
            role.permissions = list(permissions)
    db.commit()
    return created


def main() -> None:
    password = sys.argv[1] if len(sys.argv) > 1 else "admin123"
    db = SessionLocal()
    try:
        created = ensure_roles(db)
        print(f"角色权限已同步（共 {len(ROLE_PERMISSIONS)} 个，新建 {created} 个）")

        user = db.query(User).filter(User.username == "admin").first()
        if user is None:
            user = User(username="admin", role="admin", department="合规部")
            db.add(user)
        user.password_hash = hash_password(password)
        db.commit()
        print(f"admin 密码已设置: {password}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

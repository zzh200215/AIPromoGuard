"""初始化/重置 admin 账号密码。

用法:
    python scripts/init_data/init_admin.py [password]
默认密码 admin123（生产环境务必修改）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.infrastructure.database.mysql import SessionLocal
from src.models import User
from src.utils.security import hash_password


def main() -> None:
    password = sys.argv[1] if len(sys.argv) > 1 else "admin123"
    db = SessionLocal()
    try:
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

"""上线前配置核对脚本（W20）。检查生产环境高风险配置项。

用法:
    python scripts/backup/check_production.py
输出 PASS / WARN / FAIL 清单；存在 FAIL 时退出码非 0。

检查项：
- APP_DEBUG：生产环境应为 false
- JWT_SECRET：不得为默认值 change-me
- DASHSCOPE_API_KEY：不应为空（LLM 审查依赖）
- admin 账号：不应使用默认密码 admin123
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.utils.config import settings
from src.utils.security import verify_password


def _check(name: str, level: str, detail: str) -> None:
    print(f"[{level:4s}] {name}: {detail}")


def main() -> int:
    fails = warns = 0

    # 1. debug 开关
    if settings.debug:
        _check("APP_DEBUG", "WARN", "debug=true（生产应设 .env DEBUG=false）")
        warns += 1
    else:
        _check("APP_DEBUG", "PASS", "debug=false")

    # 2. JWT secret
    if not settings.jwt_secret or settings.jwt_secret == "change-me":
        _check("JWT_SECRET", "FAIL", "仍为默认值，必须改为随机长字符串")
        fails += 1
    elif len(settings.jwt_secret) < 16:
        _check("JWT_SECRET", "WARN", "长度过短，建议 ≥ 32 随机字符")
        warns += 1
    else:
        _check("JWT_SECRET", "PASS", "已配置")

    # 3. LLM Key
    if not settings.dashscope_api_key:
        _check("DASHSCOPE_API_KEY", "WARN", "为空，LLM 语义审查将降级为纯规则引擎")
        warns += 1
    else:
        _check("DASHSCOPE_API_KEY", "PASS", "已配置")

    # 4. admin 默认密码
    try:
        from src.infrastructure.database.mysql import SessionLocal
        from src.models import User

        db = SessionLocal()
        admin = db.query(User).filter(User.username == "admin").first()
        db.close()
        if admin and verify_password("admin123", admin.password_hash):
            _check("admin 密码", "FAIL", "使用默认密码 admin123，必须修改")
            fails += 1
        else:
            _check("admin 密码", "PASS", "非默认密码")
    except Exception:
        _check("admin 密码", "WARN", "无法连接数据库核验")
        warns += 1

    print(f"\n结论: {fails} FAIL / {warns} WARN，FAIL 需在上线前处理")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

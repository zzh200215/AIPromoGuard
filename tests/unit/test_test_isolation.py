"""测试隔离守卫：断言测试进程连接的是 fcr_test，而不是真库。

背景（2026-10-16 根治）：测试曾直连真库并清空演示数据。隔离由
tests/conftest.py 在 pytest 导入任何 src 模块前改写 MYSQL_DATABASE 实现；
本守卫防止 conftest 被误删/误改而无感知。若此测试失败：检查
tests/conftest.py 是否仍设置 MYSQL_DATABASE=fcr_test，并先执行
python scripts/dev/init_test_db.py 初始化测试库。
"""

from src.utils.config import settings


def test_settings_point_to_test_database():
    assert settings.mysql_database == "fcr_test", (
        f"测试进程连接了 {settings.mysql_database!r}——隔离失效！"
        "检查 tests/conftest.py 是否设置 MYSQL_DATABASE=fcr_test"
    )

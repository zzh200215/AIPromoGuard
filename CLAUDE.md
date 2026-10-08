# 项目协作约定（AI 助手必读）

## Python 环境（重要，勿搞错）

- 项目专用环境：`D:\AI\ACD\envs\llmXM`（Python 3.11，含 fastembed/pytest/python-docx 等全部依赖）。
- 运行后端测试/脚本一律用它，不要用系统 Python或其它 venv：
  - `"D:\AI\ACD\envs\llmXM\python.exe" -m pytest tests/ --basetemp=.pytest-tmp`
  - `"D:\AI\ACD\envs\llmXM\python.exe" -m ruff check .`
- 测试依赖真实 MySQL/Redis 时，连不上会自动 skip；需要完整功能时用 docker compose 起基础设施。

## 其它要点

- 前端目录 `frontend/`；mock API：`node dev-mock.mjs`（默认 8000，本机被占时 `MOCK_PORT=8001` + `VITE_API_TARGET=http://127.0.0.1:8001 npm run dev`）。
- 项目有 git 仓库（`main` 分支，2026-10-08 实测确认且持续提交中）——删除文件仍优先用 git 找回，但重构时依旧优先编辑而非整文件重写。
- **数据库 schema 变更一律走 Alembic**（权威入口 `migrations/`，2026-10-08 PR-0a 起）：
  - 新库/升级：`python -m alembic upgrade head`（docker api 容器启动时自动执行）
  - 生成迁移：`python -m alembic revision --autogenerate -m "描述"`（对开发库）
  - 漂移校验（模型改了忘写迁移会红）：`python scripts/maintenance/schema_drift_check.py`
  - 历史 `docker/init-scripts/init_mysql.sql` 与 `scripts/migrate/*.py` 均已废弃，勿再使用。

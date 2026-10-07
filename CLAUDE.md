# 项目协作约定（AI 助手必读）

## Python 环境（重要，勿搞错）

- 项目专用环境：`D:\AI\ACD\envs\llmXM`（Python 3.11，含 fastembed/pytest/python-docx 等全部依赖）。
- 运行后端测试/脚本一律用它，不要用系统 Python或其它 venv：
  - `"D:\AI\ACD\envs\llmXM\python.exe" -m pytest tests/ --basetemp=.pytest-tmp`
  - `"D:\AI\ACD\envs\llmXM\python.exe" -m ruff check .`
- 测试依赖真实 MySQL/Redis 时，连不上会自动 skip；需要完整功能时用 docker compose 起基础设施。

## 其它要点

- 前端目录 `frontend/`；mock API：`node dev-mock.mjs`（默认 8000，本机被占时 `MOCK_PORT=8001` + `VITE_API_TARGET=http://127.0.0.1:8001 npm run dev`）。
- 本项目无 git 仓库，删除文件不可恢复，重构时优先编辑而非整文件重写。

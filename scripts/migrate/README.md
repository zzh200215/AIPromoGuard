# scripts/migrate —— 已退役（历史脚本，勿再新增）

本目录是 Alembic 引入（PR-0a，2026-10-08）之前的**手写幂等迁移脚本**，
用于已有库的增量升级（新库当时靠 `Base.metadata.create_all` / init SQL 兜底）。

## 现状

**已全部退役**。schema 演进的唯一权威入口是仓库根 `migrations/`（Alembic）：

```bash
python -m alembic upgrade head                       # 已有库/新库统一入口
python -m alembic revision --autogenerate -m "描述"   # 新变更
python scripts/maintenance/schema_drift_check.py     # 漂移校验
```

## 为什么保留本目录

- 历史脚本记录了早期 schema 变更的**意图与顺序**（如 `task_profile.py` 的
  profile 列引入背景），对已有库排障有参考价值。
- 已执行过这些脚本的库不受影响；**未执行过的不需要再执行**
  （`alembic upgrade head` 一步到位）。

## 禁令

- 勿在本目录新增脚本——所有表结构变更改为 Alembic 迁移。
- 勿修改这些脚本——它们是历史快照。

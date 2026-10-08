# Alembic 迁移目录

schema 演进的唯一权威入口。所有表结构变更（建表 / 加列 / 加索引 / 加外键）
必须以迁移脚本形式提交到 `versions/`，不再使用历史做法：

| 历史做法 | 状态 |
|---|---|
| `docker/init-scripts/init_mysql.sql`（MySQL 容器首启建库） | **已废弃**（容器不再挂载；文件保留仅作历史参考） |
| `scripts/migrate/*.py`（手写幂等升级脚本） | **已退役**（勿再新增；历史脚本保留供已有库人工参考） |
| 局部 `Base.metadata.create_all` | 仅测试内局部建表保留（tests/unit/test_llm_cache.py） |

## 常用命令

```bash
python -m alembic upgrade head                       # 升级到最新（新库=建全部表）
python -m alembic revision --autogenerate -m "描述"   # 依 ORM 模型生成迁移（对开发库）
python -m alembic stamp head                         # 已有库标记为最新
python -m alembic downgrade -1                       # 回滚一步
python scripts/maintenance/schema_drift_check.py     # 漂移校验（迁移链产物 vs ORM 模型）
```

## 约定

- 生成迁移前先 `git diff` 确认模型改动符合预期；生成后**人工审阅**脚本，
  删除 autogenerate 的噪声操作（如 server_default 抖动）。
- 每个迁移必须实现对称 `downgrade()`（不可逆操作需在脚本内注释说明）。
- `langgraph_checkpoints` / `langgraph_writes` 两表不参与 autogenerate
  （见 env.py 说明），其新库快照在 0001 baseline 内。

## 老库与 Alembic 新建库的已知差异（2026-10-08 实测）

历史库（由 init SQL + scripts/migrate 逐步演进形成）与 Alembic 新建库存在以下**非行为差异**，
经 19 表逐列/逐索引对比确认，刻意保留（如需完全一致可后续单独迁移收口）：

| 差异 | 范围 | 说明 |
|---|---|---|
| `BIGINT` vs `BIGINT UNSIGNED` | 31 列（各表 id/外键列） | 老库 UNSIGNED（init SQL 风格），新库 signed（ORM 默认）。**各库内部自洽**，PR-7 加外键时同库内类型配对一致，不受影响 |
| 列注释 COMMENT | 老库多处中文列注释 | ORM 模型未声明 comment，新库无列注释；无行为影响 |
| `ON UPDATE CURRENT_TIMESTAMP` | 5 处 updated_at | 老库 DB 层自动更新；ORM 已带 `onupdate=func.now()`（应用写入时显式 SET），**应用路径行为一致**；仅裸 SQL UPDATE 场景有差异（项目内无此写法） |
| `created_at` NULL 性 | notifications / task_sign_offs 两表 | 老库可 NULL（历史建表疏漏），新库 NOT NULL（ORM 语义更严格，**方向正确**） |

**已对齐（PR-0a 修复）**：索引全量对齐（ORM 补入 13 个索引定义，含 2 处自动名
`ix_*` 改为老库显式名、1 处单列升级为复合）、server_default 26 处（`default=` 与
`server_default=` 并存）、`mysql.TINYINT` 类型 4 处。对齐后"行为相关差异"归零。

> 对齐方式为"以老库实测结构为客观事实，修正 ORM 模型"——老库结构经 344 用例与评估
> 基准长期验证，是行为基准；ORM 是它的描述，描述偏离时修描述。

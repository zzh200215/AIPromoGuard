"""应用配置：环境变量（.env 敏感项） + configs/app.yaml（非敏感项）。"""

from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_yaml(name: str) -> dict[str, Any]:
    path = PROJECT_ROOT / "configs" / name
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class Settings(BaseSettings):
    """环境变量驱动设置。字段名大写为 .env 中的键（如 MYSQL_HOST）。"""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = True

    # LLM（QWEN）
    dashscope_api_key: str = ""
    llm_model: str = "qwen-plus"
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_temperature: float = 0.2
    llm_timeout: int = 120

    # 视觉层审查（VLM，图片文档专用；走同一 DashScope 兼容端点的多模态模型）
    vlm_model: str = "qwen-vl-plus"
    vlm_enabled: bool = True

    # LLM 可观测性（Langfuse，可选：两 Key 均配置才启用，未配置时埋点 no-op）
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""

    # MySQL
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "compliance_review"

    # Redis
    redis_url: str = "redis://127.0.0.1:6379/0"

    # 异步任务队列（B2：Celery broker，为空时回退 redis_url）
    celery_broker_url: str = ""

    # 向量库
    vector_store_type: str = "chroma"  # chroma | milvus
    chroma_persist_dir: str = "./data/chroma"
    milvus_host: str = "127.0.0.1"
    milvus_port: int = 19530

    # 知识图谱（Neo4j，W9）
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j123"

    # 嵌入模型
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dim: int = 512
    embedding_cache_dir: str = "./data/models/fastembed"

    # 安全
    jwt_secret: str = ""
    jwt_access_expire_minutes: int = 120
    jwt_refresh_expire_days: int = 7

    # 存储
    upload_dir: str = "./data/uploads"
    report_dir: str = "./data/reports"

    @property
    def mysql_url(self) -> str:
        # 用户名/密码需 URL 编码：含 @ : / % 等字符时裸拼会解析错乱（连错主机/认证失败）
        return (
            f"mysql+pymysql://{quote_plus(self.mysql_user)}:{quote_plus(self.mysql_password)}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )

    def app_config(self, section: str) -> dict[str, Any]:
        """读取 configs/app.yaml 中的非敏感配置段。"""
        return _load_yaml("app.yaml").get(section, {})


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    # 确保数据目录存在
    for d in (
        settings.upload_dir,
        settings.report_dir,
        settings.chroma_persist_dir,
        settings.embedding_cache_dir,
    ):
        Path(d).mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()

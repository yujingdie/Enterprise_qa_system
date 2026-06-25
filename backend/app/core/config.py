"""
统一配置加载器
从 .env 读取私密配置，从 config/*.yml 读取业务配置
合并为全局 config 单例
"""

import os
import yaml
from pathlib import Path
from pydantic_settings import BaseSettings

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class EnvSettings(BaseSettings):
    """从 .env 加载私密配置"""

    # LLM
    llm_base_url: str = "https://api.minimaxi.com/v1"
    llm_model: str = "mimo-v2.5-pro"
    llm_api_key: str  # 必填，无默认值——未配置时 pydantic 会报错

    # Embedding
    embedding_provider: str = "qianwen"
    embedding_model: str = "text-embedding-v3"
    qianwen_api_key: str  # 必填
    qianwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # 本地 Embedding
    embedding_device: str = "cuda"

    # Milvus
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection: str = "knowledge_base"

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "knowledge_qa"

    # JWT
    jwt_secret: str  # 必填，无默认值——必须从 .env 提供
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    class Config:
        env_file = str(BASE_DIR / ".env")
        case_sensitive = False


class AppConfig:
    """全局配置单例"""

    def __init__(self):
        self.env = EnvSettings()
        self.prompts = self._load_yaml(BASE_DIR / "config" / "prompts.yml")
        self.pipeline = self._load_yaml(BASE_DIR / "config" / "pipeline.yml")

    def _load_yaml(self, path: Path) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.env.postgres_user}:"
            f"{self.env.postgres_password}@{self.env.postgres_host}:"
            f"{self.env.postgres_port}/{self.env.postgres_db}"
        )


# 全局单例
config = AppConfig()

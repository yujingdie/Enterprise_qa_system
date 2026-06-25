"""
Embedding 客户端
支持千问 API（text-embedding-v3）和本地模型（BGE-large-zh-v1.5）
通过 pipeline.yml 配置切换
"""

from openai import AsyncOpenAI
from app.core.config import config

# 本地模型（懒加载）
_local_model = None


def _get_local_model():
    """懒加载本地 Embedding 模型"""
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer

        device = config.env.embedding_device
        _local_model = SentenceTransformer(
            config.env.embedding_model, device=device
        )
    return _local_model


async def embed(texts: list[str]) -> list[list[float]]:
    """
    统一入口：将文本列表转为向量列表
    根据配置决定用本地模型还是千问 API
    """
    if config.env.embedding_provider == "local":
        return _embed_local(texts)
    else:
        return await _embed_qianwen(texts)


def embed_sync(texts: list[str]) -> list[list[float]]:
    """同步版本（测试和评估用）"""
    if config.env.embedding_provider == "local":
        return _embed_local(texts)
    else:
        import asyncio
        return asyncio.run(_embed_qianwen(texts))


def _embed_local(texts: list[str]) -> list[list[float]]:
    """本地模型：BGE / M3E"""
    model = _get_local_model()
    embeddings = model.encode(
        texts,
        batch_size=config.pipeline["embedding"]["batch_size"],
        normalize_embeddings=True,
    )
    return embeddings.tolist()


async def _embed_qianwen(texts: list[str]) -> list[list[float]]:
    """千问 Embedding API"""
    client = AsyncOpenAI(
        base_url=config.env.qianwen_base_url,
        api_key=config.env.qianwen_api_key,
    )
    response = await client.embeddings.create(
        model=config.env.embedding_model,
        input=texts,
    )
    return [item.embedding for item in response.data]

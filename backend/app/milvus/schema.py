"""
Milvus Collection Schema 定义

这是整个项目中最重要的设计文件之一。
Schema 设计直接影响：
- 检索精度（dense + sparse 双向量）
- 查询灵活性（metadata 过滤）
- 存储效率（索引策略）
"""

from pymilvus import (
    Collection,
    CollectionSchema,
    FieldSchema,
    DataType,
    utility,
)
from app.core.config import config

COLLECTION_NAME = config.pipeline["milvus"]["collection"]
DIMENSION = config.pipeline["embedding"]["dimension"]


def create_collection() -> Collection:
    """
    创建 Collection，如果已存在则直接返回。

    字段说明:
    - id: 主键，uuid
    - chunk_text: 切片的原始文本 (VARCHAR)
    - dense_vector: 语义向量 (FLOAT_VECTOR, 1024/768维)
    - doc_id: 所属文档的 ID (VARCHAR)
    - source: 文档文件名 (VARCHAR)
    - page: 页码 (INT32)
    - chunk_index: 本文档内第几个切片 (INT32)
    - user_id: 所属用户 ID (VARCHAR)
    """
    if utility.has_collection(COLLECTION_NAME):
        return Collection(COLLECTION_NAME)

    # 定义字段
    fields = [
        # 主键
        FieldSchema(
            name="id",
            dtype=DataType.VARCHAR,
            max_length=64,
            is_primary=True,
            auto_id=False,
        ),
        # 原文文本
        FieldSchema(
            name="chunk_text",
            dtype=DataType.VARCHAR,
            max_length=8192,
        ),
        # 语义向量（Dense）
        FieldSchema(
            name="dense_vector",
            dtype=DataType.FLOAT_VECTOR,
            dim=DIMENSION,
        ),
        # 元数据字段
        FieldSchema(
            name="doc_id",
            dtype=DataType.VARCHAR,
            max_length=64,
        ),
        FieldSchema(
            name="source",
            dtype=DataType.VARCHAR,
            max_length=256,
        ),
        FieldSchema(
            name="page",
            dtype=DataType.INT32,
        ),
        FieldSchema(
            name="chunk_index",
            dtype=DataType.INT32,
        ),
        # 用户归属
        FieldSchema(
            name="user_id",
            dtype=DataType.VARCHAR,
            max_length=64,
        ),
    ]

    # 定义 Schema
    schema = CollectionSchema(
        fields=fields,
        description="企业知识库 - 文档向量索引",
        enable_dynamic_field=False,
    )

    # 创建 Collection
    collection = Collection(name=COLLECTION_NAME, schema=schema)

    return collection


def get_collection() -> Collection:
    """获取已有的 Collection"""
    if not utility.has_collection(COLLECTION_NAME):
        raise RuntimeError(f"Collection '{COLLECTION_NAME}' 不存在，请先调用 create_collection()")
    return Collection(COLLECTION_NAME)

"""
Milvus 写入操作
批量写入向量数据，支持单条和批量
"""

import uuid
from pymilvus import Collection
from app.core.config import config

COLLECTION_NAME = config.pipeline["milvus"]["collection"]


def insert_batch(
    collection: Collection,
    chunks: list[dict],
) -> list[str]:
    """
    批量插入

    chunks 格式:
    [
        {
            "chunk_text": "...",
            "dense_vector": [...],
            "doc_id": "...",
            "source": "...",
            "page": 1,
            "chunk_index": 0,
        },
        ...
    ]
    返回插入的 id 列表
    """
    ids = [str(uuid.uuid4()) for _ in chunks]

    entities = []
    for i, c in enumerate(chunks):
        entities.append({
            "id": ids[i],
            "chunk_text": c["chunk_text"],
            "dense_vector": c["dense_vector"],
            "doc_id": c["doc_id"],
            "source": c["source"],
            "page": c["page"],
            "chunk_index": c["chunk_index"],
            "user_id": c.get("user_id", ""),
        })

    collection.insert(entities)
    collection.flush()
    return ids


def delete_by_doc_id(collection: Collection, doc_id: str):
    """删除指定文档的所有向量"""
    collection.delete(f'doc_id == "{doc_id}"')


def get_count(collection: Collection) -> int:
    """获取 Collection 中的记录数"""
    collection.flush()
    return collection.num_entities

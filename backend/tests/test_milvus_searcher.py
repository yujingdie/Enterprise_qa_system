"""Milvus 检索测试（需要 Milvus 运行）"""

import pytest


@pytest.mark.skip(reason="需要 Milvus 服务运行")
def test_search_dense():
    """测试语义检索"""
    from app.milvus.client import connect
    from app.milvus.schema import get_collection
    from app.milvus.searcher import search_dense
    from app.embed.client import embed_sync

    connect()
    collection = get_collection()

    query = "报销流程"
    query_vector = embed_sync([query])[0]
    results = search_dense(collection, query_vector, top_k=5)

    assert len(results) <= 5
    assert all("chunk_text" in r for r in results)
    assert all("source" in r for r in results)


@pytest.mark.skip(reason="需要 Milvus 服务运行")
def test_search_hybrid():
    """测试混合检索"""
    from app.milvus.client import connect
    from app.milvus.schema import get_collection
    from app.milvus.searcher import search_hybrid
    from app.embed.client import embed_sync

    connect()
    collection = get_collection()

    query = "公司组织架构"
    query_vector = embed_sync([query])[0]
    results = search_hybrid(collection, query_vector, top_k=5)

    assert len(results) <= 5

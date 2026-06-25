"""Embedding 客户端测试"""

from app.embed.client import embed, embed_sync


def test_embed_sync_dimension():
    """同步 Embedding 应返回正确维度"""
    vectors = embed_sync(["测试文本"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 1024


def test_embed_sync_batch():
    """批量 Embedding"""
    texts = ["第一段文本", "第二段文本", "第三段文本"]
    vectors = embed_sync(texts)
    assert len(vectors) == 3
    assert all(len(v) == 1024 for v in vectors)

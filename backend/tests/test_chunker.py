"""切分器测试"""

from app.pipeline.chunker import chunk_text


def test_fixed_chunk():
    """测试固定窗口切分"""
    text = "这是一段测试文本。" * 100
    chunks = chunk_text(text, metadata={"page": 1})
    assert len(chunks) > 1
    assert all("chunk_text" in c for c in chunks)
    assert all("page" in c for c in chunks)


def test_recursive_chunk_short():
    """递归切分：短文本不应该被切分"""
    text = "这是一个短句，不需要切分。"
    chunks = chunk_text(text, metadata={})
    assert len(chunks) == 1
    assert chunks[0]["chunk_text"] == text


def test_chunk_preserves_metadata():
    """切分后元数据应该保留"""
    text = "A" * 512 + "B" * 512
    chunks = chunk_text(text, metadata={"page": 3, "source": "test.pdf"})
    assert all(c.get("page") == 3 for c in chunks)
    assert all(c.get("source") == "test.pdf" for c in chunks)


def test_chunk_index():
    """切片索引应正确编号"""
    text = "X" * 2000
    chunks = chunk_text(text, metadata={})
    assert chunks[0]["chunk_index"] == 0

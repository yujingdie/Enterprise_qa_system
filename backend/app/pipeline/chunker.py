"""
文档切分器

切分策略：
1. fixed:      固定窗口切分（不推荐，会断句）
2. recursive:  递归切分（按标题 → 段落 → 句子）
3. semantic:   语义段落切分（按段落/句子边界，不重叠）

默认使用 semantic，通过 pipeline.yml 的 chunk.strategy 切换
"""

import re
from app.core.config import config


def chunk_text(text: str, metadata: dict = None) -> list[dict]:
    """
    统一入口：根据配置选择切分策略

    metadata 包含页面号、来源文档等，会附加到每个 chunk

    返回格式:
    [
        {
            "chunk_text": "切片文本...",
            "page": 1,
            "chunk_index": 0,
        },
    ]
    """
    strategy = config.pipeline["chunk"]["strategy"]
    chunk_size = config.pipeline["chunk"]["size"]

    if strategy == "semantic":
        chunks = _semantic_chunk(text, chunk_size)
    elif strategy == "recursive":
        overlap = config.pipeline["chunk"].get("overlap", 0)
        chunks = _recursive_chunk(text, chunk_size, overlap)
    elif strategy == "fixed":
        overlap = config.pipeline["chunk"].get("overlap", 0)
        chunks = _fixed_chunk(text, chunk_size, overlap)
    else:
        chunks = _semantic_chunk(text, chunk_size)

    # 附加元数据
    if metadata:
        for chunk in chunks:
            chunk.update(metadata)

    # 全局索引
    for i, chunk in enumerate(chunks):
        chunk["chunk_index"] = i

    return chunks


def chunk_pages(pages: list[dict], source: str, doc_id: str) -> list[dict]:
    """
    对解析后的页面列表进行切分（PDF/PPT 场景）

    pages: [{"page": 1, "text": "..."}, ...]
    """
    all_chunks = []
    for page_info in pages:
        chunks = chunk_text(
            page_info["text"],
            metadata={
                "page": page_info["page"],
                "source": source,
                "doc_id": doc_id,
            },
        )
        all_chunks.extend(chunks)

    # 全局索引
    for i, chunk in enumerate(all_chunks):
        chunk["chunk_index"] = i

    return all_chunks


# ---- 切分策略实现 ----

def _semantic_chunk(text: str, chunk_size: int) -> list[dict]:
    """
    语义段落切分：按段落/句子边界切分，不重叠

    逻辑：
    1. 按双换行拆成段落
    2. 太长的段落按句子拆开
    3. 相邻短段落合并，直到接近 chunk_size
    4. 不做 overlap
    """
    if not text or not text.strip():
        return []

    # 第一步：按段落拆分
    raw_paragraphs = re.split(r'\n\s*\n', text.strip())

    # 第二步：太长的段落按句子拆开
    segments = []
    for para in raw_paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) <= chunk_size:
            segments.append(para)
        else:
            # 按中英文句号、问号、感叹号拆句子
            parts = re.split(r'(?<=[。！？!?])', para)
            for part in parts:
                part = part.strip()
                if part:
                    segments.append(part)

    # 第三步：合并相邻短段落，不拆散已有段落
    chunks = []
    current = ""

    for seg in segments:
        # 加上新段落会不会超
        test = current + seg if not current else current + "\n\n" + seg
        if len(test) <= chunk_size:
            current = test
        else:
            if current:
                chunks.append(current)
            current = seg

    if current:
        chunks.append(current)

    return [{"chunk_text": c} for c in chunks]


def _fixed_chunk(text: str, chunk_size: int, overlap: int) -> list[dict]:
    """固定窗口切分：每 chunk_size 个字符切一刀，前后 overlap 个字符重叠"""
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append({"chunk_text": chunk_text})
        if end == len(text):
            break
        start = end - overlap

    return chunks


def _recursive_chunk(text: str, chunk_size: int, overlap: int) -> list[dict]:
    """
    递归切分：优先按自然边界切分

    分隔符优先级：
    1. 双换行（段落边界）
    2. 单换行
    3. 句号、问号、感叹号
    4. 逗号、分号
    5. 空格
    6. 字符级直接切
    """
    separators = [
        "\n\n", "\n", "。", "？", "！", "；", "，", ";", ",", " ", ""
    ]
    chunks = []

    def _split(text: str, sep_idx: int):
        nonlocal chunks
        if len(text) <= chunk_size:
            if text.strip():
                chunks.append({"chunk_text": text.strip()})
            return

        if sep_idx >= len(separators):
            # 最后手段：字符级强制切
            _fixed_texts = _fixed_chunk(text, chunk_size, overlap)
            chunks.extend(_fixed_texts)
            return

        sep = separators[sep_idx]
        if sep == "":
            # 空格作为分隔符时特殊处理
            _fixed_texts = _fixed_chunk(text, chunk_size, overlap)
            chunks.extend(_fixed_texts)
            return

        parts = text.split(sep)
        current = ""

        for part in parts:
            if len(current) + len(part) + len(sep) <= chunk_size:
                current += (sep if current else "") + part
            else:
                if current.strip():
                    # 当前块已满，递归处理
                    _split(current.strip(), sep_idx + 1)
                current = part

        if current.strip():
            _split(current.strip(), sep_idx + 1)

    _split(text, 0)
    return chunks

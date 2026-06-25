"""
入库管线

流程:
  上传文件 → 解析 → 切分 → 到 Milvus → 更新数据库状态
"""

import os
from pathlib import Path
from app.core.config import config
from app.embed.client import embed
from app.milvus.schema import get_collection
from app.milvus.writer import insert_batch, delete_by_doc_id
from app.pipeline.chunker import chunk_pages, chunk_text
from app.pipeline.parser import pdf, word, ppt, text

# 支持的文件类型
PARSER_MAP = {
    ".pdf": pdf,
    ".docx": word,
    ".doc": word,
    ".pptx": ppt,
    ".ppt": ppt,
    ".txt": text,
    ".md": text,
}

BATCH_SIZE = config.pipeline["embedding"]["batch_size"]


def get_parser(file_path: str):
    """根据文件扩展名获取对应的解析器"""
    ext = Path(file_path).suffix.lower()
    parser = PARSER_MAP.get(ext)
    if parser is None:
        raise ValueError(f"不支持的文件类型: {ext}，支持: {list(PARSER_MAP.keys())}")
    return parser, ext


async def ingest_file(file_path: str, doc_id: str, source: str, user_id: str = "") -> int:
    """
    入库单个文件

    返回: 切分后的 chunk 数量
    """
    parser, ext = get_parser(file_path)

    # === 步骤 1: 解析文档 ===
    if ext in (".pdf", ".ppt", ".pptx"):
        # 按页解析
        pages = parser.parse(file_path)
        if not pages:
            raise ValueError("文档解析结果为空，可能是不支持的格式或损坏的文件")

        # 按页切分
        chunks = chunk_pages(pages, source=source, doc_id=doc_id)

    else:
        # Word / TXT → 整体解析
        full_text = parser.parse(file_path)
        if not full_text.strip():
            raise ValueError("文档解析结果为空")

        # 切分文本
        chunk_dicts = chunk_text(full_text, metadata={
            "page": 0,  # Word/TXT 没有明确的页码
            "source": source,
            "doc_id": doc_id,
        })
        chunks = chunk_dicts

    if not chunks:
        raise ValueError("文档切分后没有有效内容")

    # === 步骤 2: 对每一段文字做 Embedding ===
    texts = [c["chunk_text"] for c in chunks]
    collection = get_collection()

    # 分批处理（避免一次请求发送太多文本）
    all_ids = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch_texts = texts[i:i + BATCH_SIZE]
        batch_chunks = chunks[i:i + BATCH_SIZE]

        # 调用 Embedding 服务
        dense_vectors = await embed(batch_texts)

        # 构建批量插入数据
        insert_data = []
        for j, chunk in enumerate(batch_chunks):
            insert_data.append({
                "chunk_text": chunk["chunk_text"],
                "dense_vector": dense_vectors[j],
                "doc_id": chunk.get("doc_id", doc_id),
                "source": chunk.get("source", source),
                "page": chunk.get("page", 0),
                "chunk_index": chunk.get("chunk_index", i + j),
                "user_id": user_id,
            })

        ids = insert_batch(collection, insert_data)
        all_ids.extend(ids)

    return len(all_ids)


async def delete_document(doc_id: str):
    """从 Milvus 中删除指定文档的所有向量"""
    collection = get_collection()
    delete_by_doc_id(collection, doc_id)

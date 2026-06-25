"""
重新入库脚本：用新的语义切分策略重新处理所有文档

使用方式（在 Docker backend 容器中运行）：
  docker-compose exec backend python -m scripts.reingest
"""

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal
from app.models.document import Document
from app.milvus.client import connect as milvus_connect
from app.milvus.schema import get_collection, create_collection
from app.milvus.writer import delete_by_doc_id
from app.pipeline.ingest import ingest_file
from pymilvus import utility, Collection


COLLECTION_NAME = "knowledge_base"


def clear_milvus():
    """清空 Milvus collection"""
    print("[1/4] 清空 Milvus collection...")
    if utility.has_collection(COLLECTION_NAME):
        col = Collection(COLLECTION_NAME)
        col.delete("id != ''")  # 删除全部数据
        col.flush()
        count = col.num_entities
        print(f"      Milvus 已清空，剩余 {count} 条")
    else:
        print("      Collection 不存在，跳过")


def get_all_documents():
    """获取所有已完成的文档"""
    db = SessionLocal()
    try:
        docs = db.query(Document).filter(Document.status == "completed").all()
        return [(d.id, d.filename, d.file_path, d.user_id) for d in docs]
    finally:
        db.close()


async def reingest_all():
    """重新入库所有文档"""
    docs = get_all_documents()
    print(f"[2/4] 找到 {len(docs)} 个已完成文档")

    if not docs:
        print("没有需要重新入库的文档")
        return

    success = 0
    fail = 0

    for i, (doc_id, filename, file_path, user_id) in enumerate(docs, 1):
        print(f"\n[{i}/{len(docs)}] {filename} ...", end=" ", flush=True)
        t0 = time.time()

        if not file_path or not os.path.exists(file_path):
            print(f"跳过（文件不存在: {file_path}）")
            fail += 1
            continue

        try:
            chunk_count = await ingest_file(
                file_path=file_path,
                doc_id=doc_id,
                source=filename,
                user_id=user_id or "",
            )
            elapsed = time.time() - t0
            print(f"✅ {chunk_count} chunks, {elapsed:.1f}s")
            success += 1
        except Exception as e:
            print(f"❌ {e}")
            fail += 1

    print(f"\n[3/4] 完成: {success} 成功, {fail} 失败")


def update_doc_counts():
    """更新 PostgreSQL 中的 chunk_count"""
    print("[4/4] 更新文档 chunk_count...")
    from app.models.user import User  # 确保外键关系加载
    from app.models.document import Document as DocModel
    db = SessionLocal()
    try:
        col = get_collection()
        docs = db.query(DocModel).filter(DocModel.status == "completed").all()
        for d in docs:
            try:
                results = col.query(
                    expr=f'doc_id == "{d.id}"',
                    output_fields=["chunk_index"],
                    limit=1000,
                )
                d.chunk_count = len(results)
            except Exception:
                pass
        db.commit()
        print(f"      已更新 {len(docs)} 个文档的 chunk_count")
    finally:
        db.close()


def main():
    print("=" * 50)
    print("重新入库脚本（语义切分策略）")
    print("=" * 50)

    # 连接 Milvus
    print("连接 Milvus...")
    milvus_connect()

    # 确保 Milvus collection 存在
    create_collection()

    clear_milvus()
    asyncio.run(reingest_all())
    update_doc_counts()

    # 最终统计
    col = get_collection()
    from app.milvus.writer import get_count
    total = get_count(col)
    print(f"\n📊 Milvus 总向量数: {total}")
    print("完成！")


if __name__ == "__main__":
    main()

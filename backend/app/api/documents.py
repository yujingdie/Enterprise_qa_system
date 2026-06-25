"""
文档管理接口：上传、列表、删除
"""

import os
import uuid
import logging
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, get_db
from app.models.document import Document
from app.schemas.document import DocumentResponse, DocumentListResponse, DocumentDeleteResponse
from app.pipeline.ingest import ingest_file, delete_document
from app.core.database import SessionLocal
from app.milvus.client import connect as milvus_connect

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["文档管理"])

# 上传文件存储目录
UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 允许的文件类型
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".txt", ".md"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


async def _ingest_background(doc_id: str, file_path: str, source: str, user_id: str):
    """后台入库任务：解析→切分→Embedding→写入 Milvus"""
    milvus_connect()  # 后台任务需要确保 Milvus 连接
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return
        chunk_count = await ingest_file(
            file_path=file_path,
            doc_id=doc_id,
            source=source,
            user_id=user_id,
        )
        doc.chunk_count = chunk_count
        doc.status = "completed"
        db.commit()
        logger.info(f"[ingest] {source} 入库完成, {chunk_count} chunks")
    except Exception as e:
        logger.error(f"[ingest] {source} 入库失败: {e}")
        try:
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.status = "failed"
                doc.error_message = str(e)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.post("/upload", response_model=DocumentResponse)
async def upload(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传文档并自动入库（后台异步）"""
    # 校验文件类型
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {ext}，支持: {list(ALLOWED_EXTENSIONS)}",
        )

    # 保存文件（按用户分目录）
    file_id = str(uuid.uuid4())
    save_name = f"{file_id}{ext}"
    user_dir = UPLOAD_DIR / user_id
    os.makedirs(user_dir, exist_ok=True)
    save_path = user_dir / save_name

    content = await file.read()

    # 校验文件大小
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过 50MB 限制")

    with open(save_path, "wb") as f:
        f.write(content)

    # 创建文档记录（status=processing）
    doc = Document(
        user_id=user_id,
        filename=file.filename,
        file_path=str(save_path),
        file_size=len(content),
        file_type=ext.lstrip("."),
        status="processing",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # 后台入库（不阻塞响应）
    background_tasks.add_task(
        _ingest_background,
        doc_id=doc.id,
        file_path=str(save_path),
        source=file.filename,
        user_id=user_id,
    )

    return DocumentResponse(
        id=doc.id,
        filename=doc.filename,
        file_size=doc.file_size,
        file_type=doc.file_type,
        chunk_count=doc.chunk_count,
        status=doc.status,
        created_at=doc.created_at.isoformat() if doc.created_at else "",
    )


@router.get("/list", response_model=DocumentListResponse)
def list_documents(
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前用户的文档列表"""
    docs = (
        db.query(Document)
        .filter(Document.user_id == user_id)
        .order_by(Document.created_at.desc())
        .all()
    )

    return DocumentListResponse(
        documents=[
            DocumentResponse(
                id=d.id,
                filename=d.filename,
                file_size=d.file_size,
                file_type=d.file_type,
                chunk_count=d.chunk_count,
                status=d.status,
                created_at=d.created_at.isoformat() if d.created_at else "",
            )
            for d in docs
        ],
        total=len(docs),
    )


@router.delete("/{doc_id}", response_model=DocumentDeleteResponse)
async def delete(
    doc_id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除文档（同时从 Milvus 中删除对应向量）"""
    doc = db.query(Document).filter(
        Document.id == doc_id,
        Document.user_id == user_id,
    ).first()

    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 删除 Milvus 中的向量
    try:
        await delete_document(doc_id)
    except Exception:
        pass  # Milvus 删除失败不阻塞

    # 删除本地文件
    try:
        os.remove(doc.file_path)
    except OSError:
        pass

    # 删除数据库记录
    db.delete(doc)
    db.commit()

    return DocumentDeleteResponse(message="文档已删除", deleted_id=doc_id)

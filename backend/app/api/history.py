"""
历史记录接口
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, get_db
from app.models.conversation import Conversation
from app.schemas.qa import HistoryItem, SourceInfo

router = APIRouter(prefix="/api/history", tags=["历史记录"])


@router.get("")
def get_history(
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前用户的问答历史"""
    total = (
        db.query(Conversation)
        .filter(Conversation.user_id == user_id)
        .count()
    )

    records = (
        db.query(Conversation)
        .filter(Conversation.user_id == user_id)
        .order_by(Conversation.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    items = []
    for r in records:
        sources = [
            SourceInfo(
                doc_name=s.get("doc_name", ""),
                page=s.get("page", 0),
                score=s.get("score", 0),
                chunk_text=s.get("chunk_text", ""),
            )
            for s in (r.sources or [])
        ]

        items.append(
            HistoryItem(
                id=r.id,
                question=r.question,
                answer=r.answer,
                sources=sources,
                created_at=r.created_at.isoformat() if r.created_at else "",
            )
        )

    return {"items": items, "total": total}

"""
会话管理接口
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession
from app.api.deps import get_current_user, get_db
from app.models.session import Session
from app.models.conversation import Conversation
from app.schemas.session import (
    SessionCreate,
    SessionUpdate,
    SessionResponse,
    SessionDetail,
    ConversationMessage,
)

router = APIRouter(prefix="/api/sessions", tags=["会话管理"])


@router.post("", response_model=SessionResponse)
def create_session(
    req: SessionCreate,
    user_id: str = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    session = Session(user_id=user_id, title=req.title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return _to_response(session)


@router.get("")
def list_sessions(
    user_id: str = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    sessions = (
        db.query(Session)
        .filter(Session.user_id == user_id)
        .order_by(Session.updated_at.desc())
        .all()
    )
    return {"items": [_to_response(s) for s in sessions]}


@router.get("/{session_id}", response_model=SessionDetail)
def get_session(
    session_id: str,
    user_id: str = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    session = _get_owned_session(db, session_id, user_id)

    conversations = (
        db.query(Conversation)
        .filter(Conversation.session_id == session_id)
        .order_by(Conversation.created_at.asc())
        .all()
    )

    messages = [
        ConversationMessage(
            id=c.id,
            question=c.question,
            answer=c.answer,
            sources=c.sources or [],
            created_at=c.created_at.isoformat() if c.created_at else "",
        )
        for c in conversations
    ]

    return SessionDetail(session=_to_response(session), messages=messages)


@router.patch("/{session_id}", response_model=SessionResponse)
def rename_session(
    session_id: str,
    req: SessionUpdate,
    user_id: str = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    session = _get_owned_session(db, session_id, user_id)
    session.title = req.title
    db.commit()
    db.refresh(session)
    return _to_response(session)


@router.delete("/{session_id}")
def delete_session(
    session_id: str,
    user_id: str = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    session = _get_owned_session(db, session_id, user_id)
    # 删除关联的对话记录
    db.query(Conversation).filter(Conversation.session_id == session_id).delete()
    db.delete(session)
    db.commit()
    return {"ok": True}


def _get_owned_session(db: DBSession, session_id: str, user_id: str) -> Session:
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session or session.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return session


def _to_response(s: Session) -> SessionResponse:
    return SessionResponse(
        id=s.id,
        title=s.title,
        created_at=s.created_at.isoformat() if s.created_at else "",
        updated_at=s.updated_at.isoformat() if s.updated_at else "",
    )

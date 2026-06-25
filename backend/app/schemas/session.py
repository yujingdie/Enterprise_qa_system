"""会话相关请求/响应模型"""

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    title: str = Field(default="新对话", max_length=200)


class SessionUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class SessionResponse(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class ConversationMessage(BaseModel):
    id: str
    question: str
    answer: str
    sources: list[dict] = []
    created_at: str


class SessionDetail(BaseModel):
    session: SessionResponse
    messages: list[ConversationMessage]

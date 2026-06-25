"""文档相关请求/响应模型"""

from pydantic import BaseModel, Field


class DocumentResponse(BaseModel):
    id: str
    filename: str
    file_size: int
    file_type: str
    chunk_count: int
    status: str
    created_at: str


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int


class DocumentDeleteResponse(BaseModel):
    message: str
    deleted_id: str

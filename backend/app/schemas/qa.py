"""问答相关请求/响应模型"""

from pydantic import BaseModel, Field


class SourceInfo(BaseModel):
    doc_name: str = Field(..., description="文档名称")
    page: int = Field(..., description="页码")
    score: float = Field(..., description="相关度分数")
    chunk_text: str = Field(..., description="原文片段")


class HistoryItem(BaseModel):
    id: str = Field(..., description="记录ID")
    question: str = Field(..., description="用户问题")
    answer: str = Field(..., description="回答内容")
    sources: list[SourceInfo] = Field(default_factory=list, description="引用来源")
    created_at: str = Field(..., description="创建时间")

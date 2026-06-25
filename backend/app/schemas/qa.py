"""问答相关请求/响应模型"""

from pydantic import BaseModel, Field


class SourceInfo(BaseModel):
    doc_name: str = Field(..., description="文档名称")
    page: int = Field(..., description="页码")
    score: float = Field(..., description="相关度分数")
    chunk_text: str = Field(..., description="原文片段")

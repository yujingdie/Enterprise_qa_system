"""
重排序器

使用 Cross-encoder 模型对 Milvus 检索结果做精排。
Bi-encoder（Milvus Embedding）快但粗，Cross-encoder 慢但准。
先粗筛（Milvus Top 20）→ 再精排（Reranker Top 5）。

如果 sentence-transformers 未安装，rerank 函数会跳过并返回原结果。
"""

import logging
import math
from app.core.config import config

logger = logging.getLogger(__name__)

_reranker = None
_HAS_RERANKER = False

try:
    from sentence_transformers import CrossEncoder
    _HAS_RERANKER = True
except ImportError:
    CrossEncoder = None


def _get_model():
    """懒加载 Reranker 模型（优先从本地路径加载）"""
    global _reranker
    if _reranker is None and _HAS_RERANKER:
        import os
        # 优先使用本地预下载的模型
        local_path = "/app/reranker_model"
        if os.path.exists(os.path.join(local_path, "config.json")):
            model_name = local_path
            logger.info("reranker: loading from local path %s", model_name)
        else:
            model_name = config.pipeline["reranker"]["model"]
            logger.info("reranker: downloading model %s", model_name)
        _reranker = CrossEncoder(model_name)
    return _reranker


def rerank(
    query: str,
    candidates: list[dict],
    top_k: int = None,
) -> list[dict]:
    """
    对 Milvus 检索结果重新排序

    参数:
    - query: 用户原始问题
    - candidates: Milvus 返回的列表，每项需含 "chunk_text"
    - top_k: 最终返回多少条

    返回: 重新排序后的列表，score 字段会更新
    """
    if top_k is None:
        top_k = config.pipeline["retrieval"]["rerank_top_k"]

    if not candidates:
        return []

    if not _HAS_RERANKER:
        return candidates[:top_k]

    model = _get_model()
    if model is None:
        return candidates[:top_k]

    # 构建 (query, document) 对
    pairs = [[query, c["chunk_text"]] for c in candidates]

    # 批量打分
    scores = model.predict(pairs)

    # 按新分数排序（sigmoid 归一化到 0~1）
    for i, candidate in enumerate(candidates):
        raw = float(scores[i])
        candidate["rerank_score"] = 1 / (1 + math.exp(-raw))  # sigmoid

    ranked = sorted(candidates, key=lambda x: x["rerank_score"], reverse=True)

    # 返回 top_k
    results = ranked[:top_k]

    # 统一 score 字段
    for r in results:
        r["score"] = r["rerank_score"]

    return results

"""
Milvus 检索操作

三种检索方式：
1. search_dense:   纯语义检索（Dense Vector）
2. search_sparse:  纯关键词检索（Sparse Vector）
3. search_hybrid:  混合检索（Dense + Sparse + RRF 融合）
"""

from pymilvus import Collection, AnnSearchRequest, WeightedRanker, RRFRanker
from app.core.config import config


def _ensure_loaded(collection: Collection):
    """确保 Collection 已加载到内存（幂等操作）"""
    try:
        if not collection.is_loaded:
            collection.load(timeout=30000)
    except Exception:
        pass  # load 可能已由其他进程完成


def search_dense(
    collection: Collection,
    query_vector: list[float],
    top_k: int = None,
    user_id: str = None,
) -> list[dict]:
    """
    纯语义检索
    使用 Dense 向量做 ANN 搜索，适合自然语言问题
    """
    _ensure_loaded(collection)
    if top_k is None:
        top_k = config.pipeline["retrieval"]["top_k"]

    search_params = {
        "metric_type": "COSINE",
        "params": {"ef": config.pipeline["milvus"]["hnsw"]["ef_search"]},
    }

    kwargs = dict(
        data=[query_vector],
        anns_field="dense_vector",
        param=search_params,
        limit=top_k,
        output_fields=["chunk_text", "doc_id", "source", "page", "chunk_index"],
    )
    if user_id:
        kwargs["expr"] = f'user_id == "{user_id}"'

    results = collection.search(**kwargs)

    return _format_results(results[0])


def search_hybrid(
    collection: Collection,
    query_vector: list[float],
    sparse_vector: dict = None,
    top_k: int = None,
    use_rerank: bool = True,
    user_id: str = None,
) -> list[dict]:
    """
    混合检索：Dense + Sparse 融合

    流程:
    1. 分别用 Dense 和 Sparse 向量各搜 top_k 条
    2. 用 RRF（Reciprocal Rank Fusion）融合排序
    3. 取融合后的 top_k 条

    RRF 公式: score(d) = Σ 1/(k + rank_i(d))
    其中 k=60（默认），rank_i 是文档在第 i 个排序列表中的排名
    """
    _ensure_loaded(collection)
    if top_k is None:
        top_k = config.pipeline["retrieval"]["top_k"]

    search_params_dense = {
        "metric_type": "COSINE",
        "params": {"ef": config.pipeline["milvus"]["hnsw"]["ef_search"]},
    }

    # Dense 搜索请求
    dense_req = AnnSearchRequest(
        data=[query_vector],
        anns_field="dense_vector",
        param=search_params_dense,
        limit=top_k * 2,  # 多取一些，给 RRF 更大的融合空间
    )

    requests = [dense_req]

    # 如果提供了 sparse 向量，加入混合检索
    if sparse_vector and config.pipeline["retrieval"]["use_sparse"]:
        search_params_sparse = {"metric_type": "IP"}
        sparse_req = AnnSearchRequest(
            data=[sparse_vector],
            anns_field="sparse_vector",
            param=search_params_sparse,
            limit=top_k * 2,
        )
        requests.append(sparse_req)

    # RRF 融合
    ranker = RRFRanker(k=60)

    kwargs = dict(
        reqs=requests,
        rerank=ranker,
        limit=top_k,
        output_fields=["chunk_text", "doc_id", "source", "page", "chunk_index"],
    )
    if user_id:
        kwargs["expr"] = f'user_id == "{user_id}"'

    results = collection.hybrid_search(**kwargs)

    return _format_results(results[0])


def _format_results(hits) -> list[dict]:
    """将 Milvus 搜索结果格式化为统一结构"""
    return [
        {
            "id": hit.id,
            "score": hit.distance,
            "chunk_text": hit.fields.get("chunk_text", ""),
            "doc_id": hit.fields.get("doc_id", ""),
            "source": hit.fields.get("source", ""),
            "page": hit.fields.get("page", 0),
            "chunk_index": hit.fields.get("chunk_index", 0),
        }
        for hit in hits
    ]

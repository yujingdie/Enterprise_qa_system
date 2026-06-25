"""
查询管线

流程:
  用户问题 → Query 改写 → 向量检索 → Rerank → LLM 生成答案

拆分为:
  run_retrieval()  — 检索阶段（改写+检索+重排），返回候选文档
  build_messages() — 构建多轮对话消息列表
  run_query()      — 完整管线（检索 + 非流式生成），向后兼容
"""

import json
import logging
import time
from app.core.config import config
from app.llm.client import chat as llm_chat
from app.embed.client import embed
from app.milvus.schema import get_collection
from app.milvus.searcher import search_dense
from app.pipeline.reranker import rerank

logger = logging.getLogger(__name__)


async def run_retrieval(question: str, user_id: str = None) -> dict:
    """
    检索阶段：Query 改写 → 向量检索 → Rerank

    返回: {
        "candidates": [...],       # 原始候选文档
        "sources": [...],          # 格式化后的来源信息
        "context": str,            # 拼接好的参考资料文本
        "rewrite_queries": [...],  # 改写后的查询
    }
    """
    # === 步骤 1: Query 改写（判断+按需改写，一次 LLM 调用） ===
    t0 = time.time()
    rewriter_prompt = config.prompts["query_rewrite"]["system"]
    rewrite_queries = [question]  # 默认只用原始问题
    try:
        rewrite_result = await llm_chat(
            system_prompt=rewriter_prompt,
            user_message=f"用户原始问题：{question}",
            temperature=0.3,
        )
        parsed = _parse_rewrite_result(rewrite_result)
        if parsed["need_rewrite"]:
            rewrite_queries = parsed["queries"]
            if question not in rewrite_queries:
                rewrite_queries.insert(0, question)
            logger.info("query_rewrite: need_rewrite=True, %d queries in %.2fs",
                        len(rewrite_queries), time.time() - t0)
        else:
            logger.info("query_rewrite: need_rewrite=False, using original query in %.2fs",
                        time.time() - t0)
    except Exception:
        logger.warning("query_rewrite failed, fallback to original query", exc_info=True)

    # === 步骤 2: 向量检索 + 文件名匹配 ===
    t1 = time.time()
    all_candidates = {}
    collection = get_collection()

    for query in rewrite_queries:
        try:
            query_vector = await embed([query])
        except Exception:
            logger.warning("embedding failed for query: %s", query[:50], exc_info=True)
            continue
        try:
            results = search_dense(
                collection,
                query_vector[0],
                top_k=config.pipeline["retrieval"]["top_k"],
                user_id=user_id,
            )
        except Exception:
            logger.warning("milvus search failed for query: %s", query[:50], exc_info=True)
            continue
        for r in results:
            if r["id"] not in all_candidates or r["score"] > all_candidates[r["id"]]["score"]:
                all_candidates[r["id"]] = r

    candidates = sorted(
        all_candidates.values(), key=lambda x: x["score"], reverse=True
    )[:config.pipeline["retrieval"]["top_k"]]
    logger.info("retrieval: %d candidates in %.2fs", len(candidates), time.time() - t1)

    # === 步骤 3: 重排序 ===
    if config.pipeline["reranker"]["enabled"] and len(candidates) > 1:
        t2 = time.time()
        try:
            rerank_top_k = config.pipeline["retrieval"]["rerank_top_k"]
            candidates = rerank(question, candidates, top_k=rerank_top_k)
            logger.info("rerank: %d results in %.2fs", len(candidates), time.time() - t2)
        except Exception:
            candidates = candidates[:config.pipeline["retrieval"]["rerank_top_k"]]
            logger.warning("rerank failed, fallback to score sort", exc_info=True)

    # 过滤低分结果
    threshold = config.pipeline["retrieval"]["score_threshold"]
    logger.info("threshold=%.2f, pre-filter scores: %s",
                threshold,
                [(c["source"][:30], round(c["score"], 4)) for c in candidates])
    candidates = [c for c in candidates if c["score"] >= threshold]

    # 构建来源和上下文
    sources = [
        {
            "doc_name": c["source"],
            "page": c["page"],
            "score": round(c["score"], 4),
            "chunk_text": c["chunk_text"][:300],
        }
        for c in candidates
    ]

    context_parts = []
    for i, c in enumerate(candidates):
        context_parts.append(
            f"[资料{i+1}] 来源：{c['source']} 第{c['page']}页\n{c['chunk_text']}"
        )
    context = "\n\n".join(context_parts)

    return {
        "candidates": candidates,
        "sources": sources,
        "context": context,
        "rewrite_queries": rewrite_queries,
    }


def build_messages(
    history: list[dict] | None, question: str, context: str
) -> list[dict]:
    """
    构建多轮对话消息列表，用于 LLM 流式生成。

    history: [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]
    context:  RAG 检索到的参考资料文本
    返回: Anthropic messages 格式的消息列表
    """
    messages = []

    # 加入历史对话（最近 10 轮）
    if history:
        for turn in history[-10:]:
            messages.append({"role": turn["role"], "content": turn["content"]})

    # 当前问题附带参考资料
    user_content = f"参考资料：\n{context}\n\n用户问题：{question}" if context else question
    messages.append({"role": "user", "content": user_content})

    return messages


def get_answer_prompt(context: str) -> str:
    """获取答案生成的 system prompt（带参考资料注入）"""
    return config.prompts["answer_generate"]["system"].format(context=context)


async def run_query(question: str, history: list[dict] | None = None, user_id: str = None) -> dict:
    """
    完整查询管线（非流式），向后兼容。

    返回: {"answer": "...", "sources": [...], "rewrite_queries": [...]}
    """
    retrieval = await run_retrieval(question, user_id=user_id)

    if not retrieval["candidates"]:
        return {
            "answer": "抱歉，在知识库中没有找到与您问题相关的资料。请尝试换个方式提问，或上传相关文档。",
            "sources": [],
            "rewrite_queries": retrieval["rewrite_queries"],
        }

    # 构建消息并调用 LLM
    messages = build_messages(history, question, retrieval["context"])
    answer_prompt = get_answer_prompt(retrieval["context"])

    try:
        answer = await llm_chat(
            system_prompt=answer_prompt,
            user_message=messages[-1]["content"],
            temperature=0.3,
        )
    except Exception:
        answer = "（LLM 服务暂不可用）以下是根据知识库检索到的相关资料：\n\n" + "\n\n".join(
            f"- [{c['source']} 第{c['page']}页] {c['chunk_text'][:200]}"
            for c in retrieval["candidates"][:3]
        )

    return {
        "answer": answer,
        "sources": retrieval["sources"],
        "rewrite_queries": retrieval["rewrite_queries"],
    }


def _parse_rewrite_result(raw: str) -> dict:
    """
    解析 LLM 改写的 JSON 输出。

    返回: {"need_rewrite": bool, "queries": [...]}
    """
    default = {"need_rewrite": False, "queries": []}
    try:
        data = json.loads(raw)
        if not data.get("need_rewrite", False):
            return {"need_rewrite": False, "queries": []}
        queries = data.get("queries", [])
        if queries:
            return {"need_rewrite": True, "queries": queries[:3]}
        return default
    except json.JSONDecodeError:
        pass

    # 尝试从文本中提取 JSON
    import re
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            if not data.get("need_rewrite", False):
                return {"need_rewrite": False, "queries": []}
            queries = data.get("queries", [])
            if queries:
                return {"need_rewrite": True, "queries": queries[:3]}
            return default
        except json.JSONDecodeError:
            pass

    # 兜底：解析失败，不改写，用原始问题
    return default

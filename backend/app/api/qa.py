"""
问答接口 — SSE 流式响应（Agent 模式）

流程:
  用户提问 → Agent Loop（LLM 自主决策调用工具，最多 4 轮）→ 流式输出答案

工具:
  - search_knowledge_base: 向量检索知识库
  - search_by_filename: 按文件名精确读取文档内容
  - list_documents: 列出所有已上传文档
"""

import json
import logging
import re
import asyncio
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DBSession

from app.api.deps import get_current_user, get_db
from app.core.config import config
from app.core.database import SessionLocal
from app.llm.client import chat, chat_stream_with_history
from app.milvus.schema import get_collection
from app.milvus.searcher import search_dense
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.session import Session
from app.embed.client import embed
from app.pipeline.query import _parse_rewrite_result

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/qa", tags=["问答"])

MAX_TOOL_ROUNDS = 4

# ---------- 工具定义 ----------

TOOLS = [
    {
        "name": "search_knowledge_base",
        "description": "在企业知识库中进行语义向量搜索，返回最相关的文档片段。适合回答一般性问题。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或问题",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_by_filename",
        "description": "根据文件名精确读取某个文档的全部内容。当用户明确提到某个文件/文档名称时使用。",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "文件名或文件名关键词（如 '课表'、'就业协议书'）",
                }
            },
            "required": ["filename"],
        },
    },
    {
        "name": "list_documents",
        "description": "列出知识库中所有已上传的文档名称。当用户询问有哪些文档、或想了解知识库内容时使用。",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]

AGENT_SYSTEM_PROMPT = """\
你是一个专业的企业知识问答助手。你可以使用以下工具来查找信息：

1. search_knowledge_base — 语义搜索知识库（默认首选）
2. search_by_filename — 根据文件名精确读取文档内容
3. list_documents — 列出所有已上传的文档

核心规则：
- 必须基于工具返回的真实资料回答，不能编造任何信息
- 默认用 search_knowledge_base 搜索
- 当用户明确提到文件名（如"claude.md"、"那个xx文件"）时，用 search_by_filename 精确读取
- 当用户要求"列出所有文档"时，用 list_documents
- 如果工具返回"搜索结果为空"或参考资料与问题无关，直接回复"知识库不存在对应内容，请上传相关文件"，不要列举文档类型或给建议
- 当你已经通过工具获取了足够的信息时，必须立即停止调用工具，直接用自然语言总结回答。每个问题最多调用1-2次工具即可。
- 绝对不要在回答中输出 tool_call、function_call、<tool_call>、<function>、<parameter> 等任何XML或工具调用格式的文本，只输出自然语言回答
- 不要在回答中输出"来源：xxx"、"《xxx》第X页"、"（参考：xxx）"等来源引用信息，系统会在回答下方自动以卡片形式展示参考来源及相似度分数
- 回答使用 Markdown 格式，禁止输出 HTML 标签
- 回答简洁清晰
"""


# ---------- 工具执行 ----------

async def _exec_search_knowledge_base(query: str, user_id: str) -> str:
    """
    纯向量检索 + Reranker 精排（不做 query 改写）

    流程：Embedding → Milvus 粗排 Top 20 → 阈值过滤 → Reranker 精排 Top 5
    """
    try:
        from app.pipeline.reranker import rerank

        collection = get_collection()
        top_k = config.pipeline["retrieval"]["top_k"]
        threshold = config.pipeline["retrieval"]["score_threshold"]
        rerank_threshold = config.pipeline["retrieval"]["rerank_score_threshold"]
        rerank_top_k = config.pipeline["retrieval"]["rerank_top_k"]

        # Embedding
        query_vector = await embed([query])

        # Milvus 粗排
        results = search_dense(collection, query_vector[0], top_k=top_k, user_id=user_id)
        logger.info("search[%s]: Milvus raw=%d, scores=%s",
                     query[:30], len(results),
                     [round(r["score"], 4) for r in results[:5]])

        # 粗排阈值过滤
        before = len(results)
        results = [r for r in results if r["score"] >= threshold]
        logger.info("search[%s]: after_dense_threshold=%.2f %d/%d",
                     query[:30], threshold, len(results), before)

        if not results:
            return "搜索结果为空，未找到相关内容。"

        # Reranker 精排 Top 5
        try:
            results = rerank(query, results, top_k=rerank_top_k)
        except Exception:
            results = sorted(results, key=lambda x: x["score"], reverse=True)[:rerank_top_k]

        # 精排阈值过滤
        before = len(results)
        results = [r for r in results if r["score"] >= rerank_threshold]
        logger.info("search[%s]: after_rerank_threshold=%.2f %d/%d",
                     query[:30], rerank_threshold, len(results), before)

        if not results:
            return "搜索结果为空，未找到相关内容。"

        parts = []
        for i, r in enumerate(results, 1):
            parts.append(
                f"[资料{i}] 来源：{r['source']} 第{r['page']}页 "
                f"(相关度: {r['score']:.2f})\n{r['chunk_text']}"
            )
        return "\n\n".join(parts)
    except Exception as e:
        logger.error("search_knowledge_base failed: %s", e)
        return f"搜索出错：{e}"


async def _exec_search_by_filename(filename: str, user_id: str, question: str = "") -> str:
    """按文件名读取文档内容 → Reranker 精排 → Top K"""
    db = SessionLocal()
    try:
        from app.pipeline.reranker import rerank

        docs = db.query(Document).filter(
            Document.user_id == user_id,
            Document.status == "completed",
        ).all()

        # 匹配优先级：精确 > 前缀 > 包含
        matched = None
        name_lower = filename.lower()
        for doc in docs:
            fname = doc.filename.rsplit(".", 1)[0].lower()
            if fname == name_lower:
                matched = doc
                break
        if not matched:
            for doc in docs:
                fname = doc.filename.rsplit(".", 1)[0].lower()
                if fname.startswith(name_lower) or name_lower.startswith(fname):
                    matched = doc
                    break
        if not matched:
            for doc in docs:
                fname = doc.filename.rsplit(".", 1)[0].lower()
                if name_lower in fname or fname in name_lower:
                    matched = doc
                    break

        if not matched:
            available = [d.filename for d in docs]
            return f"未找到名为 '{filename}' 的文档。可用文档：{', '.join(available[:10])}"

        # 从 Milvus 读取该文档 chunks（粗排上限）
        collection = get_collection()
        top_k = config.pipeline["retrieval"]["top_k"]
        chunks = collection.query(
            expr=f'doc_id == "{matched.id}"',
            output_fields=["chunk_text", "doc_id", "source", "page", "chunk_index"],
            limit=top_k,
        )
        chunks.sort(key=lambda x: x.get("chunk_index", 0))

        if not chunks:
            return f"文档 '{matched.filename}' 暂无已索引的内容。"

        # 转成 candidates 格式，用 reranker 精排
        candidates = [
            {
                "id": f"{c.get('doc_id', '')}_{c.get('chunk_index', 0)}",
                "score": 0.85,
                "chunk_text": c.get("chunk_text", ""),
                "source": c.get("source", matched.filename),
                "page": c.get("page", 0),
            }
            for c in chunks
        ]

        # Reranker 精排
        rerank_top_k = config.pipeline["retrieval"]["rerank_top_k"]
        query_for_rerank = question or filename
        try:
            candidates = rerank(query_for_rerank, candidates, top_k=rerank_top_k)
        except Exception:
            candidates = candidates[:rerank_top_k]

        parts = []
        for i, c in enumerate(candidates, 1):
            parts.append(
                f"[资料{i}] 来源：{c['source']} 第{c['page']}页 "
                f"(相关度: {c['score']:.2f})\n{c['chunk_text']}"
            )
        return "\n\n".join(parts)
    except Exception as e:
        logger.error("search_by_filename failed: %s", e)
        return f"读取文档出错：{e}"
    finally:
        db.close()


def _exec_list_documents(user_id: str) -> str:
    """列出所有已上传文档"""
    db = SessionLocal()
    try:
        docs = db.query(Document).filter(
            Document.user_id == user_id,
            Document.status == "completed",
        ).all()
        if not docs:
            return "知识库中暂无已上传的文档。"
        names = [d.filename for d in docs]
        return f"知识库中共有 {len(names)} 个文档：\n" + "\n".join(
            f"- {n}" for n in names
        )
    finally:
        db.close()


async def _execute_tool(name: str, args: dict, user_id: str, question: str = "") -> str:
    if name == "search_knowledge_base":
        return await _exec_search_knowledge_base(args.get("query", ""), user_id)
    elif name == "search_by_filename":
        return await _exec_search_by_filename(args.get("filename", ""), user_id, question)
    elif name == "list_documents":
        return _exec_list_documents(user_id)
    else:
        return f"未知工具：{name}"


# ---------- 文本 tool_call 解析（MiMo 等模型会把 tool_call 写成纯文本） ----------

# 匹配 <tool_call>...</tool_call> 或 <function=name>...</function> 格式
_XML_TC_RE = re.compile(
    r"<tool_call>\s*"
    r"<name>(.*?)</name>\s*"
    r"<parameters>(.*?)</parameters>\s*"
    r"</tool_call>",
    re.DOTALL,
)
_FUNC_RE = re.compile(
    r"<function=(\w+)>(.*?)</function>",
    re.DOTALL,
)
_PARAM_RE = re.compile(r"<(\w+)>(.*?)</\1>", re.DOTALL)

_VALID_TOOL_NAMES = {t["name"] for t in TOOLS}


def _parse_text_tool_calls(text: str) -> list[dict] | None:
    """尝试从纯文本中提取 MiMo 等模型写出的 XML 格式 tool_call。"""
    calls = []

    for m in _XML_TC_RE.finditer(text):
        name = m.group(1).strip()
        params_xml = m.group(2)
        if name not in _VALID_TOOL_NAMES:
            continue
        args = {p.group(1): p.group(2).strip() for p in _PARAM_RE.finditer(params_xml)}
        calls.append({"name": name, "args": args})

    if not calls:
        for m in _FUNC_RE.finditer(text):
            name = m.group(1).strip()
            params_xml = m.group(2)
            if name not in _VALID_TOOL_NAMES:
                continue
            args = {p.group(1): p.group(2).strip() for p in _PARAM_RE.finditer(params_xml)}
            calls.append({"name": name, "args": args})

    return calls if calls else None


# ---------- Agent Loop ----------

async def _agent_loop_to_queue(question: str, user_id: str, history: list[dict] | None = None,
                               queue: asyncio.Queue | None = None):
    """Agent Loop → 把事件放入 Queue（支持 Task 取消）"""
    try:
        async for event in _agent_loop(question, user_id, history):
            await queue.put(event)
    except asyncio.CancelledError:
        pass
    finally:
        await queue.put(None)  # 结束标记


async def _agent_loop(question: str, user_id: str, history: list[dict] | None = None):
    """
    Agent Loop：
    1. Query 改写判断（不带工具）→ 确定搜索策略
    2. 直接搜索（不经过 LLM 工具调用）
    3. 流式输出答案
    """
    messages = []
    # 加入历史对话（最近 10 轮）
    if history:
        for turn in history[-10:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": question})

    # === Step 1: Query 改写判断（不带工具） ===
    yield _sse_event("tool_call", {
        "name": "analyze_question",
        "args": {},
        "result": "正在分析问题",
    })

    search_queries = [question]
    try:
        rewriter_prompt = config.prompts["query_rewrite"]["system"]
        rewrite_result = await chat(
            system_prompt=rewriter_prompt,
            user_message=f"用户原始问题：{question}",
            temperature=0.3,
        )
        parsed = _parse_rewrite_result(rewrite_result)
        if parsed["need_rewrite"]:
            queries = parsed["queries"][:2]
            # 原始问题 + 改写（去重）
            search_queries = [question] + [q for q in queries if q != question]
            logger.info("query_rewrite: need_rewrite=True, queries=%s", search_queries)
        else:
            logger.info("query_rewrite: need_rewrite=False, using original query")
    except Exception:
        logger.warning("query_rewrite failed, fallback to original query", exc_info=True)

    # === Step 2: 直接搜索（每个 query 各搜一次） ===
    all_sources = {}
    combined_context_parts = []

    for i, query in enumerate(search_queries):
        # 通知前端正在搜索
        yield _sse_event("tool_call", {
            "name": "search_knowledge_base",
            "args": {"query": query[:50]},
            "result": f"正在搜索 ({i+1}/{len(search_queries)})",
        })

        result_text = await _exec_search_knowledge_base(query, user_id)
        if not result_text or result_text.startswith("搜索结果为空"):
            continue

        # 提取来源信息
        new_sources = _extract_sources_from_result(result_text)
        for s in new_sources:
            key = f"{s['doc_name']}_{s['page']}"
            if key not in all_sources or s["score"] > all_sources[key]["score"]:
                all_sources[key] = s

        combined_context_parts.append(result_text)

    if not all_sources:
        yield _sse_event("answer",
            "抱歉，在知识库中没有找到与您问题相关的资料。请尝试换个方式提问，或上传相关文档。")
        return

    # 去重 + 排序 + top 5
    sources_list = sorted(all_sources.values(), key=lambda x: x["score"], reverse=True)[:5]

    # === Step 3: 流式生成答案 ===
    context = "\n\n".join(combined_context_parts)

    answer_prompt = config.prompts["answer_generate"]["system"].format(context=context)

    # 用带上下文的 user message 替换原问题
    messages[-1] = {
        "role": "user",
        "content": f"参考资料：\n{context}\n\n用户问题：{question}",
    }

    full_answer = ""
    try:
        async for chunk in chat_stream_with_history(
            messages=messages,
            system_prompt=answer_prompt,
            temperature=0.3,
        ):
            full_answer += chunk
            yield _sse_event("answer", chunk)
    except Exception as e:
        logger.error("Agent final answer stream failed: %s", e)
        yield _sse_event("answer", "（生成答案时出错）")
        return

    # 答案输出完后再发 sources（如果 LLM 说未找到，就不展示来源）
    not_found_keywords = ["未找到", "没有找到", "暂无", "没有相关", "未发现", "不存在对应内容"]
    is_not_found = any(kw in full_answer for kw in not_found_keywords)
    if sources_list and not is_not_found:
        yield _sse_event("sources", sources_list)


# ---------- SSE 工具函数 ----------

def _sse_event(event: str, data) -> str:
    """格式化 SSE 事件"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _sanitize_answer(text: str) -> str:
    """清理 LLM 输出中的 HTML 标签、Anthropic XML、tool_call 残留和内联来源引用"""
    # 移除完整的 tool_call block
    text = re.sub(r"<function=[^>]*>.*?</parameter>", "", text, flags=re.DOTALL | re.IGNORECASE)

    # cleanup XML tags
    text = re.sub(r'</?function[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?parameter[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?tool_call[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?parameters[^>]*>', '', text, flags=re.IGNORECASE)

    # 移除 Anthropic XML 标签（antml:parameter、antml:tool_result 等）
    text = re.sub(r'</?antml:[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?function[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?invoke[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?tool_result[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?tool_call[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?parameters[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?parameter[^>]*>', '', text, flags=re.IGNORECASE)

    # 移除常见 HTML 标签但保留内容
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</?p[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</?(?:div|span|section|article|header|footer|main|aside)[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?(?:ul|ol|li|dl|dt|dd)[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?(?:h[1-6])[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?(?:table|tr|td|th|thead|tbody)[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?(?:strong|b|em|i|u|s|del|ins|mark|small|sub|sup)[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?(?:a|img|video|audio|iframe|embed|object)[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?(?:pre|code|blockquote|hr|br|hr/)[^>]*>', '', text, flags=re.IGNORECASE)
    # 兜底：移除剩余的 HTML 标签
    text = re.sub(r'<[^>]+>', '', text)

    # 移除内联来源引用（来源由前端卡片组件展示，不应出现在回答文本中）
    # 匹配: 来源：《xxx》第25-26页、《xxx》第26页
    text = re.sub(r'\n*\s*来源：《[^》]*》[^《]*?(?:、《[^》]*》[^《]*?)*\s*$', '', text)
    # 匹配: 参考来源：《xxx》...
    text = re.sub(r'\n*\s*参考来源[:：].*$', '', text, flags=re.MULTILINE)
    # 匹配: （来源：xxx）或 (来源：xxx)
    text = re.sub(r'[（(]来源[:：][^)）]*[)）]', '', text)
    # 匹配单独一行的"来源：xxx"（整行都是来源引用）
    text = re.sub(r'^\s*来源[:：].*$', '', text, flags=re.MULTILINE)

    # 清理多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _extract_sources_from_result(result_text: str) -> list[dict]:
    """
    从工具返回的文本中提取来源信息。
    支持两种格式：
    - search_knowledge_base: [资料1] 来源：xxx.pdf 第1页 (相关度: 0.85)
    - search_by_filename: [xxx.pdf 第1页]
    """
    sources = []
    seen = set()

    # 格式1: 向量搜索结果
    for match in re.finditer(r'\[资料\d+\] 来源：(.+?) 第(\d+)页.*?\(相关度: ([\d.]+)\)', result_text):
        key = f"{match.group(1)}_{match.group(2)}"
        if key not in seen:
            seen.add(key)
            sources.append({
                "doc_name": match.group(1),
                "page": int(match.group(2)),
                "score": float(match.group(3)),
            })

    # 格式2: 文件名搜索结果（没有 score，给默认 1.0 表示精确匹配）
    for match in re.finditer(r'\[(.+?) 第(\d+)页\]', result_text):
        key = f"{match.group(1)}_{match.group(2)}"
        if key not in seen:
            seen.add(key)
            sources.append({
                "doc_name": match.group(1),
                "page": int(match.group(2)),
                "score": 1.0,
            })

    return sources


# ---------- 接口 ----------

@router.post("/ask")
async def ask(
    req_body: dict,
    user_id: str = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """问答接口：SSE 流式返回"""
    question = req_body.get("question", "").strip()
    session_id = req_body.get("session_id")

    if not question:
        return {"error": "问题不能为空"}, 400

    # 处理会话
    if session_id:
        session = db.query(Session).filter(
            Session.id == session_id,
            Session.user_id == user_id,
        ).first()
        if not session:
            return {"error": "会话不存在"}, 404
    else:
        session = Session(
            user_id=user_id,
            title=question[:50],
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        session_id = session.id

    # 获取历史对话
    conversations = (
        db.query(Conversation)
        .filter(Conversation.session_id == session_id)
        .order_by(Conversation.created_at.asc())
        .all()
    )
    history = []
    for c in conversations:
        history.append({"role": "user", "content": c.question})
        history.append({"role": "assistant", "content": c.answer})

    # 更新会话标题（如果还是默认值）
    if session.title == "新对话":
        session.title = question[:50]
        db.commit()

    async def event_generator():
        """SSE 事件生成器（支持客户端断开时真正中断）"""
        full_answer = ""
        sources_data = []
        disconnected = False
        queue = asyncio.Queue()

        # 在独立 Task 中运行 agent loop，断开时可直接 cancel
        agent_task = asyncio.create_task(
            _agent_loop_to_queue(question, user_id, history, queue)
        )

        try:
            while True:
                event_str = await queue.get()
                if event_str is None:
                    break  # agent loop 正常结束

                if disconnected:
                    break

                # 对 answer 事件做清理，过滤 tool_call XML 等乱七八糟的内容
                lines = event_str.strip().split("\n")
                evt_type = ""
                evt_data = ""
                for line in lines:
                    if line.startswith("event: "):
                        evt_type = line[7:].strip()
                    elif line.startswith("data: "):
                        evt_data = line[6:]

                if evt_type == "answer":
                    try:
                        chunk = json.loads(evt_data)
                    except (json.JSONDecodeError, TypeError):
                        chunk = evt_data
                    clean_chunk = _sanitize_answer(chunk)
                    if not clean_chunk:
                        continue  # chunk 全是 XML，跳过
                    full_answer += clean_chunk
                    event_str = _sse_event("answer", clean_chunk)

                try:
                    yield event_str
                except (ConnectionResetError, BrokenPipeError, GeneratorExit):
                    logger.info("Client disconnected, stopping stream")
                    disconnected = True
                    agent_task.cancel()
                    break

                if evt_type == "sources":
                    try:
                        sources_data = json.loads(evt_data)
                    except (json.JSONDecodeError, TypeError):
                        pass

        except (ConnectionResetError, BrokenPipeError, GeneratorExit):
            logger.info("Client disconnected")
            disconnected = True
            if not agent_task.done():
                agent_task.cancel()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if not disconnected:
                logger.error("SSE event generator error: %s", e)
                try:
                    yield _sse_event("answer", "\n\n（服务异常，请稍后重试）")
                except Exception:
                    pass

        # 清理答案中的 HTML 标签
        clean_answer = _sanitize_answer(full_answer)

        # 持久化对话记录
        try:
            conv = Conversation(
                user_id=user_id,
                session_id=session_id,
                question=question,
                answer=clean_answer,
                sources=sources_data if sources_data else [],
                rewrite_queries=[],
            )
            db.add(conv)

            # 更新会话时间
            from datetime import datetime, timezone
            session.updated_at = datetime.now(timezone.utc)
            db.commit()
        except Exception as e:
            logger.error("Failed to save conversation: %s", e)
            db.rollback()

        yield _sse_event("done", {"session_id": session_id})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

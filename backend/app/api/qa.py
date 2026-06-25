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
from app.llm.client import chat_with_tools, chat_stream_with_history
from app.milvus.schema import get_collection
from app.milvus.searcher import search_dense
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.session import Session
from app.embed.client import embed

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
- 对 search_knowledge_base 的调用策略：简单明确的问题直接调用一次；复杂或模糊的问题，从两个不同角度改写成新的查询词，加上原文一共调用3次（原文+改写1+改写2）
- 如果工具返回"搜索结果为空"或参考资料与问题无关，直接回复"知识库不存在对应内容，请上传相关文件"，不要列举文档类型或给建议
- 绝对不要在回答文本中输出 tool_call、function_call、<parameter> 等工具调用格式的文本，只输出自然语言回答
- 不要在回答文本中输出"来源：xxx"、"《xxx》第X页"、"（参考：xxx）"等来源引用信息，系统会在回答下方自动以卡片形式展示参考来源及相似度分数
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
        threshold = _config.pipeline["retrieval"]["score_threshold"]
        rerank_top_k = _config.pipeline["retrieval"]["rerank_top_k"]

        # Embedding
        query_vector = await embed([query])

        # Milvus 粗排
        results = search_dense(collection, query_vector[0], top_k=top_k, user_id=user_id)

        # 阈值过滤
        results = [r for r in results if r["score"] >= threshold]

        if not results:
            return "搜索结果为空，未找到相关内容。"

        # Reranker 精排 Top 5
        try:
            results = rerank(query, results, top_k=rerank_top_k)
        except Exception:
            results = sorted(results, key=lambda x: x["score"], reverse=True)[:rerank_top_k]

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
    Agent Loop：LLM 自主决策调用工具，最多 MAX_TOOL_ROUNDS 轮。
    Yields SSE 事件字符串。
    客户端断开时，外部通过 Task.cancel() 中断此协程。
    """
    messages = []
    # 加入历史对话（最近 10 轮）
    if history:
        for turn in history[-10:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": question})

    all_sources = []

    for round_idx in range(MAX_TOOL_ROUNDS):
        try:
            response = await chat_with_tools(
                messages=messages,
                system_prompt=AGENT_SYSTEM_PROMPT,
                tools=TOOLS,
                temperature=0.3,
            )
        except Exception as e:
            logger.error("Agent loop round %d LLM call failed: %s", round_idx + 1, e)
            yield _sse_event("answer", "（LLM 服务暂不可用）")
            return

        # 检查是否有工具调用
        tool_calls = [b for b in response.content if b.type == "tool_use"]
        text_blocks = [b for b in response.content if b.type == "text"]

        if tool_calls:
            # 有工具调用：执行工具并收集结果（不管 stop_reason 是什么）
            # 先把 assistant 消息（含 tool_use）加入 messages
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for tc in tool_calls:
                tool_name = tc.name
                tool_args = tc.input
                logger.info("Agent round %d: tool=%s args=%s", round_idx + 1, tool_name, tool_args)

                # 通知前端正在执行工具
                yield _sse_event("tool_call", {
                    "name": tool_name,
                    "args": tool_args,
                    "round": round_idx + 1,
                })

                result_text = await _execute_tool(tool_name, tool_args, user_id, question)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result_text,
                })

                # 收集来源信息（多次搜索的结果合并，不覆盖）
                if tool_name in ("search_knowledge_base", "search_by_filename"):
                    new_sources = _extract_sources_from_result(result_text)
                    existing = {f"{s['doc_name']}_{s['page']}": s for s in all_sources}
                    for s in new_sources:
                        key = f"{s['doc_name']}_{s['page']}"
                        if key not in existing or s["score"] > existing[key]["score"]:
                            existing[key] = s
                    all_sources = list(existing.values())

            # 把工具结果加入 messages，进入下一轮
            messages.append({"role": "user", "content": tool_results})
        else:
            # 没有工具调用，LLM 给出了最终答案 → 流式输出
            not_found_keywords = ["未找到", "没有找到", "暂无", "没有相关", "未发现", "不存在对应内容"]
            preview_text = text_blocks[0].text if text_blocks else ""
            is_not_found = any(kw in preview_text for kw in not_found_keywords)

            if all_sources and not is_not_found:
                yield _sse_event("sources", all_sources)

            try:
                async for chunk in chat_stream_with_history(
                    messages=messages,
                    system_prompt=AGENT_SYSTEM_PROMPT,
                    temperature=0.3,
                ):
                    yield _sse_event("answer", chunk)
            except Exception as e:
                logger.error("Agent final answer stream failed: %s", e)
                yield _sse_event("answer", preview_text or "（生成答案时出错）")
            return

    # 达到最大轮数，强制 LLM 流式输出最终答案（不带工具）
    logger.warning("Agent loop reached max rounds (%d), forcing final answer", MAX_TOOL_ROUNDS)
    try:
        if all_sources:
            yield _sse_event("sources", all_sources)

        forced_system = AGENT_SYSTEM_PROMPT + (
            "\n\n【重要】你已经收集了足够的信息。"
            "请直接用自然语言回答用户问题，不要输出任何 tool_call、function_call、XML 格式的内容。"
            "只输出 Markdown 格式的自然语言回答。"
        )
        async for chunk in chat_stream_with_history(
            messages=messages,
            system_prompt=forced_system,
            temperature=0.3,
        ):
            yield _sse_event("answer", chunk)
    except Exception as e:
        logger.error("Agent loop final answer failed: %s", e)
        yield _sse_event("answer", "（LLM 服务暂不可用）")


# ---------- SSE 工具函数 ----------

def _sse_event(event: str, data) -> str:
    """格式化 SSE 事件"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _sanitize_answer(text: str) -> str:
    """清理 LLM 输出中的 HTML 标签、Anthropic XML 和内联来源引用"""
    # 移除 Anthropic XML 标签（antml:parameter、antml:tool_result 等）
    text = re.sub(r'</?antml:[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?function[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?invoke[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?tool_result[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<parameter>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</parameter>', '', text, flags=re.IGNORECASE)

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

                try:
                    yield event_str
                except (ConnectionResetError, BrokenPipeError, GeneratorExit):
                    logger.info("Client disconnected, stopping stream")
                    disconnected = True
                    agent_task.cancel()
                    break

                # 解析事件
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
                    full_answer += chunk
                elif evt_type == "sources":
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

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
你是一个专业的企业知识问答助手。你可以使用 search_knowledge_base 工具来搜索知识库。

工作流程：
1. 收到用户问题后，先判断问题是否模糊、宽泛或指代不明
2. 如果问题模糊 → 改写成**2 个不同角度**的搜索词，然后**一次性调用 search_knowledge_base 3 次**（原问题 + 2 个改写词）
3. 如果问题明确具体 → 调用 **search_knowledge_base 1 次**（用原问题即可）
4. 查看所有搜索结果，然后基于搜索结果总结回答

改写示例：
- "作者的游戏经历" → 改写为 ["作者的游戏经历", "作者玩的游戏", "作者和游戏的故事"]
- "那个软件架构的东西" → 改写为 ["软件架构", "系统架构设计", "架构方案"]
- "原神好玩吗" → 不改写（问题明确，直接搜一次）

核心规则：
- 必须基于工具返回的真实资料回答，不能编造数据
- 如果工具返回"搜索结果为空"，直接回复"知识库不存在对应内容，请上传相关文件"
- 如果搜索结果不够充分，可以换一批搜索词再次搜索
- **允许在阈值达标的搜索资料基础上做合理推断**。如果搜索结果中包含相关介绍但无法直接回答用户的问题（如用户问"我最喜欢哪个"，你搜到了多个选项的介绍），可以基于真实文档内容进行推测。但必须明确区分"资料原文"和"你的推断"，用"可能"、"推测"等措辞，绝不能编造文档中不存在的数据。
- 不确认的信息不要写死，要用"可能"、"推测"等措辞
- 看到所有搜索结果后，用自然语言总结回答
- 绝对不要在回答中输出 tool_call、function_call、<tool_call>、<function>、<parameter> 等任何XML或工具调用格式的文本，只输出自然语言回答
- 不要在回答中输出"来源：xxx"、"《xxx》第X页"、"（参考：xxx）"等来源引用信息，系统会在回答下方自动以卡片形式展示参考来源及相似度分数
- 回答使用 Markdown 格式，禁止输出 HTML 标签
- 回答简洁清晰

其他工具：
- search_by_filename — 根据文件名精确读取文档内容（当用户明确提到文件名时使用）
- list_documents — 列出所有已上传的文档（当用户询问"有哪些文档"时使用）"""


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

        logger.info("search[%s]: after_rerank scores=%s",
                     query[:30], [round(r["score"], 4) for r in results])

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
    LangChain Agent Loop（两阶段）：

    Phase 1 — 工具决策：
      LLM 通过 chat_with_tools() 自主判断是否需要改写搜索词。
      - 模糊问题：一次性调 search_knowledge_base 3 次（原 query + 2 个改写词）
      - 明确问题：调 1 次
      看到所有搜索结果后决定是否还需更多，或给出文本回答。

    Phase 2 — 流式答案输出：
      将所有搜索结果拼入上下文，流式输出。

    消息格式：OpenAI style（tool_calls + tool_result），由 client.py 统一转换。
    """
    messages = []
    if history:
        for turn in history[-10:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": question})

    all_sources = {}
    all_raw_results: list[str] = []
    tool_round = 0
    llm_raw_answer = ""

    while tool_round < MAX_TOOL_ROUNDS:
        tool_round += 1

        response = await chat_with_tools(
            messages=messages,
            system_prompt=AGENT_SYSTEM_PROMPT,
            tools=TOOLS,
            temperature=0.3,
        )

        # 检查是否有工具调用
        if response.tool_calls:
            # 把 assistant 的 tool_calls 追加到消息历史
            messages.append({
                "role": "assistant",
                "content": response.text or "",
                "tool_calls": [
                    {"id": tc["id"], "name": tc["name"], "args": tc["args"]}
                    for tc in response.tool_calls
                ],
            })

            for tc in response.tool_calls:
                tool_name = tc["name"]
                tool_args = tc["args"]
                tc_id = tc["id"]

                # 通知前端
                yield _sse_event("tool_call", {
                    "name": tool_name,
                    "args": tool_args,
                    "result": f"正在调用 {tool_name}",
                })

                result_text = await _execute_tool(tool_name, tool_args, user_id, question)
                if result_text and not result_text.startswith("搜索结果为空"):
                    all_raw_results.append(result_text)

                new_sources = _extract_sources_from_result(result_text)
                for s in new_sources:
                    key = f"{s['doc_name']}_{s['page']}"
                    if key not in all_sources or s["score"] > all_sources[key]["score"]:
                        all_sources[key] = s

                # 工具结果 -> OpenAI style tool message
                messages.append({
                    "role": "tool",
                    "content": result_text,
                    "tool_call_id": tc_id,
                })

            continue

        # 文本回复 -> LLM 认为够了
        if response.text:
            messages.append({"role": "assistant", "content": response.text})
            llm_raw_answer = response.text
            break

        # 既无工具调用也无文本 -> 异常
        raise RuntimeError("LLM response empty: no text and no tool_calls")

    # ========== Phase 2: 流式输出最终答案 ==========

    if all_sources:
        stream_messages = []
        if history:
            for turn in history[-10:]:
                stream_messages.append({"role": turn["role"], "content": turn["content"]})

        context_str = "\n\n=======\n\n".join(all_raw_results) if all_raw_results else ""
        answer_prompt = config.prompts["answer_generate"]["system"].format(context=context_str)
        stream_messages.append({
            "role": "user",
            "content": f"参考资料：\n{context_str}\n\n用户问题：{question}",
        })

        full_answer = ""
        try:
            async for chunk in chat_stream_with_history(
                messages=stream_messages,
                system_prompt="你是一个专业的企业知识问答助手。根据搜索结果回答用户问题。不要输出来源引用信息。",
                temperature=0.3,
            ):
                clean_chunk = _sanitize_answer(chunk)
                if clean_chunk:
                    full_answer += clean_chunk
                    yield _sse_event("answer", clean_chunk)
        except Exception as e:
            logger.error("Agent streaming answer failed: %s", e)
            if llm_raw_answer:
                clean = _sanitize_answer(llm_raw_answer)
                if clean:
                    yield _sse_event("answer", clean)
            else:
                yield _sse_event("answer", "（生成答案时出错）")

        not_found_keywords = ["未找到", "没有找到", "暂无", "没有相关", "未发现", "不存在对应内容"]
        is_not_found = any(kw in full_answer for kw in not_found_keywords)
        if not is_not_found:
            yield _sse_event("sources", sorted(all_sources.values(), key=lambda x: x["score"], reverse=True)[:5])
        return

    if llm_raw_answer:
        clean = _sanitize_answer(llm_raw_answer)
        if clean:
            yield _sse_event("answer", clean)
        return

    yield _sse_event("answer", "抱歉，未能获取足够的信息，请尝试换个方式提问。")


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
    text = re.sub(r'\n*\s*来源：《[^》]*》[^《]*?(?:、《[^》]*》[^《]*?)*\s*$', '', text)
    text = re.sub(r'\n*\s*参考来源[:：].*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'[（(]来源[:：][^)）]*[)）]', '', text)
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

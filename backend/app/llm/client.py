"""
LLM 调用客户端
使用 LangChain + ChatOpenAI 调用 DeepSeek (OpenAI 兼容接口)

对外接口（与旧版 Anthropic SDK 兼容）：
  chat(system_prompt, user_message) → str
  chat_with_tools(messages, system_prompt, tools) → ToolCallResponse
  chat_stream_with_history(messages, system_prompt) → AsyncGenerator[str]
"""

import json
import logging
from dataclasses import dataclass, field
from typing import AsyncGenerator

from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
    AIMessage,
    ToolMessage,
)

from app.core.config import config

logger = logging.getLogger(__name__)

_client: ChatOpenAI | None = None


# ---------- 统一响应类型 ----------


@dataclass
class ToolCallResponse:
    """chat_with_tools 的统一返回值"""
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)  # [{id, name, args}]


# ---------- 客户端 ----------


def get_client() -> ChatOpenAI:
    global _client
    if _client is None:
        _client = ChatOpenAI(
            base_url=config.env.llm_base_url,
            model=config.env.llm_model,
            api_key=config.env.llm_api_key,
            temperature=0.3,
            max_tokens=2048,
            timeout=120,
        )
    return _client


# ---------- 消息格式转换 ----------


def _build_lc_messages(
    messages: list[dict],
    system_prompt: str | None = None,
) -> list:
    """
    将通用 dict 消息转为 LangChain 消息对象列表。

    LangChain 0.3.x tool_calls 格式（扁平，无 function 嵌套）：
      AIMessage(content="", tool_calls=[{"id": "...", "name": "...", "args": {...}}])
      ToolMessage(content="...", tool_call_id="...")

    传入格式（OpenAI style）：
      {"role": "assistant", "content": "...", "tool_calls": [{"id": x, "name": x, "args": x}]}
      {"role": "tool", "content": "...", "tool_call_id": "..."}
    """
    lc: list = []
    if system_prompt:
        lc.append(SystemMessage(content=system_prompt))
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")

        if role == "user":
            lc.append(HumanMessage(content=content))
        elif role == "assistant":
            tool_calls = m.get("tool_calls", [])
            if tool_calls:
                # LangChain 0.3.x 扁平格式：{id, name, args}
                lc.append(AIMessage(
                    content=content or "",
                    tool_calls=[
                        {"id": tc["id"], "name": tc["name"], "args": tc["args"]}
                        for tc in tool_calls
                    ],
                ))
            else:
                lc.append(AIMessage(content=content))
        elif role == "tool":
            lc.append(ToolMessage(content=content, tool_call_id=m.get("tool_call_id", "")))
        else:
            lc.append(HumanMessage(content=content))
    return lc


def _parse_lc_response(response) -> ToolCallResponse:
    """将 LangChain invoke 返回值解析为 ToolCallResponse"""
    text = response.content if isinstance(response.content, str) else ""
    tool_calls = []
    if hasattr(response, "tool_calls") and response.tool_calls:
        for tc in response.tool_calls:
            # LangChain 0.3.x 扁平格式：{id, name, args}
            args = tc.get("args", {})
            if not args:
                # 兜底：从 "arguments" JSON 字符串解析
                try:
                    args = json.loads(tc.get("arguments", "{}"))
                except (json.JSONDecodeError, TypeError):
                    args = {}
            tool_calls.append({
                "id": tc.get("id", ""),
                "name": tc.get("name", ""),
                "args": args,
            })
    return ToolCallResponse(text=text, tool_calls=tool_calls)


def _convert_tools(tools: list[dict]) -> list[dict]:
    """将 Anthropic 格式工具声明转为 OpenAI/LangChain 格式"""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            },
        }
        for t in tools
    ]


# ---------- 公开 API ----------


async def chat(
    system_prompt: str, user_message: str, temperature: float = 0.3
) -> str:
    """单轮对话：发送 system + user，返回 assistant 回复"""
    client = get_client()
    logger.info("LLM chat: model=%s", config.env.llm_model)
    response = await client.ainvoke(
        _build_lc_messages(
            [{"role": "user", "content": user_message}],
            system_prompt,
        ),
    )
    result = response.content or ""
    logger.info("LLM chat done: result_len=%d", len(result))
    return result


async def chat_with_tools(
    messages: list[dict],
    system_prompt: str,
    tools: list[dict],
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> ToolCallResponse:
    """
    带工具的对话。
    messages 和 system_prompt 使用通用 dict 格式。
    返回 ToolCallResponse（含 .text 和 .tool_calls）。
    """
    client = get_client()
    lc_tools = _convert_tools(tools)
    logger.info("LLM chat_with_tools: model=%s tools=%d msgs=%d",
                config.env.llm_model, len(lc_tools), len(messages))
    response = await client.ainvoke(
        _build_lc_messages(messages, system_prompt),
        tools=lc_tools,
    )
    parsed = _parse_lc_response(response)
    logger.info("LLM chat_with_tools done: text_len=%d tool_calls=%d",
                len(parsed.text), len(parsed.tool_calls))
    return parsed


async def chat_stream_with_history(
    messages: list[dict],
    system_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> AsyncGenerator[str, None]:
    """
    带完整历史的流式对话（无 tools）。
    接受通用 dict 格式的消息列表，yield 文本 chunk。
    """
    client = get_client()
    logger.info("LLM stream_with_history: model=%s msgs=%d",
                config.env.llm_model, len(messages))
    chunk_count = 0
    try:
        async for chunk in client.astream(
            _build_lc_messages(messages, system_prompt),
        ):
            text = chunk.content or ""
            if text:
                chunk_count += 1
                yield text
    except Exception as e:
        logger.error("LLM stream error after %d chunks: %s: %s",
                     chunk_count, type(e).__name__, e)
        raise
    logger.info("LLM stream done: %d chunks", chunk_count)

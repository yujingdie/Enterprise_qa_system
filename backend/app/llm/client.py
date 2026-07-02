"""
LLM 调用客户端
使用 Anthropic SDK 调用 MiMo 2.5 Pro (Anthropic 兼容接口)
"""

import logging
import httpx
from anthropic import AsyncAnthropic
from app.core.config import config

logger = logging.getLogger(__name__)

_client: AsyncAnthropic | None = None

# 超时配置（秒）：连接超时 / 读超时 / 写超时
_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)


def get_client() -> AsyncAnthropic:
    """获取 LLM 客户端单例"""
    global _client
    if _client is None:
        _client = AsyncAnthropic(
            base_url=config.env.llm_base_url,
            api_key=config.env.llm_api_key,
            timeout=_TIMEOUT,
        )
    return _client


async def chat(
    system_prompt: str, user_message: str, temperature: float = 0.3
) -> str:
    """单轮对话：发送 system + user，返回 assistant 回复"""
    client = get_client()
    logger.info("LLM chat: model=%s sys_len=%d user_len=%d",
                config.env.llm_model, len(system_prompt), len(user_message))
    response = await client.messages.create(
        model=config.env.llm_model,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_message},
        ],
        temperature=temperature,
        max_tokens=2048,
    )
    # 兼容 ThinkingBlock（DeepSeek 等模型可能先返回推理过程再返回文本）
    result = ""
    for block in response.content:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            result = getattr(block, "text", "")
            break
    if not result:
        # 兜底：取最后一个有 input_text 的 block（tool_use 场景）
        result = response.content[-1].input_text if hasattr(response.content[-1], "input_text") else ""
    logger.info("LLM chat done: result_len=%d", len(result))
    return result


async def chat_with_tools(
    messages: list[dict],
    system_prompt: str,
    tools: list[dict],
    temperature: float = 0.3,
    max_tokens: int = 2048,
):
    """
    带工具的对话：返回 Anthropic API 的原始 response 对象。
    调用方可通过 response.content 判断是文本回复还是 tool_use 请求。
    """
    client = get_client()
    logger.info("LLM chat_with_tools: model=%s tools=%d msgs=%d",
                config.env.llm_model, len(tools), len(messages))
    response = await client.messages.create(
        model=config.env.llm_model,
        system=system_prompt,
        messages=messages,
        tools=tools,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    logger.info("LLM chat_with_tools done: stop_reason=%s content_blocks=%d",
                response.stop_reason, len(response.content))
    return response


async def chat_stream_with_history(
    messages: list[dict],
    system_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 2048,
):
    """
    带完整历史的流式对话（无 tools）。
    接受 Anthropic 格式的消息列表（含 tool_result），yield 文本 chunk。
    """
    client = get_client()
    logger.info("LLM stream_with_history: model=%s msgs=%d",
                config.env.llm_model, len(messages))
    chunk_count = 0
    try:
        async with client.messages.stream(
            model=config.env.llm_model,
            system=system_prompt,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        ) as stream:
            async for text in stream.text_stream:
                chunk_count += 1
                yield text
    except Exception as e:
        logger.error("LLM stream_with_history error after %d chunks: %s: %s",
                     chunk_count, type(e).__name__, e)
        raise
    logger.info("LLM stream_with_history done: %d chunks", chunk_count)

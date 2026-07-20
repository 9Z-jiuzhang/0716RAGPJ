"""LLM 异步调用封装：兼容 OpenAI Chat Completions 协议。

支持本项目 .env 中的 MiniMax（LLM_BASE_URL=https://api.minimaxi.com/v1）
以及其他 OpenAI 兼容网关（vLLM / Ollama / 通义兼容模式等）。

设计要点：
- 全程 httpx 异步，避免阻塞 FastAPI 事件循环；
- stream=True 时按 SSE 行解析 delta.content，供问答流水线透传；
- 非流式接口用于查询改写、会话摘要等短任务。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMServiceError(Exception):
    """LLM 调用失败时抛出的业务异常。"""

    def __init__(self, message: str, *, status_code: int | None = None, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class LLMService:
    """OpenAI 兼容协议的大模型客户端。

    可选覆盖参数用于构建 Guard、Query 预处理等独立轻量客户端。覆盖项为空时
    自动复用主 LLM 配置，因此无需重复填写密钥，同时仍能隔离模型、超时和连接池。
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        api_base: str | None = None,
        api_key: str | None = None,
        timeout_seconds: int | None = None,
        default_max_tokens: int | None = None,
    ) -> None:
        self._model_override = (model or "").strip() or None
        self._api_base_override = (api_base or "").strip() or None
        self._api_key_override = (api_key or "").strip() or None
        self._timeout_override = timeout_seconds
        self._default_max_tokens = default_max_tokens
        self._client: httpx.AsyncClient | None = None

    @property
    def api_base(self) -> str:
        """规范化 API Base，去掉末尾斜杠。"""
        base = self._api_base_override or settings.llm_api_base_resolved or "https://api.openai.com/v1"
        return base.rstrip("/")

    @property
    def model(self) -> str:
        return self._model_override or settings.LLM_MODEL

    @property
    def timeout_seconds(self) -> int:
        """返回该客户端自己的超时，避免轻量任务继承主回答的长超时。"""
        return self._timeout_override or settings.LLM_TIMEOUT_SECONDS

    def _ensure_api_key(self) -> str:
        """校验 API Key 已配置。"""
        key = self._api_key_override or (settings.LLM_API_KEY or "").strip()
        if not key:
            raise LLMServiceError("LLM_API_KEY 未配置，无法调用大模型")
        return key

    async def _get_client(self) -> httpx.AsyncClient:
        """懒加载共享 AsyncClient，复用连接池。"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds, connect=min(10.0, float(self.timeout_seconds))),
                headers={
                    "Authorization": f"Bearer {self._ensure_api_key()}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def aclose(self) -> None:
        """释放 HTTP 连接池（应用关闭时调用）。"""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stream: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """组装 Chat Completions 请求体。"""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
            "max_tokens": max_tokens or self._default_max_tokens or settings.LLM_MAX_TOKENS,
        }
        if extra:
            payload.update(extra)
        return payload

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        """
        非流式对话：返回完整助手文本。

        适用于查询改写、记忆摘要等需要一次性结果的场景。
        """
        client = await self._get_client()
        url = f"{self.api_base}/chat/completions"
        payload = self._build_payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            extra=extra,
        )
        try:
            response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMServiceError(f"LLM 请求超时（>{self.timeout_seconds}s）") from exc
        except httpx.HTTPError as exc:
            raise LLMServiceError(f"LLM 网络错误: {exc}") from exc

        if response.status_code >= 400:
            raise LLMServiceError(
                f"LLM 调用失败 HTTP {response.status_code}",
                status_code=response.status_code,
                detail=self._safe_error_body(response),
            )

        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMServiceError("LLM 响应格式异常，缺少 choices[0].message.content", detail=data) from exc
        return (content or "").strip()

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        extra: dict[str, Any] | None = None,
        usage_sink: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """
        流式对话：逐段 yield 增量文本（delta.content）。

        调用方应组装为 SSE event: chunk 推送给前端。

        传入 ``usage_sink`` 字典时，会请求上游返回 token 用量
        （OpenAI 兼容的 ``stream_options.include_usage``），并在收到
        usage 块后写入 ``usage_sink``（prompt_tokens/completion_tokens/total_tokens），
        供 Langfuse 用量追踪使用。
        """
        client = await self._get_client()
        url = f"{self.api_base}/chat/completions"
        stream_extra = dict(extra or {})
        if usage_sink is not None:
            stream_extra.setdefault("stream_options", {"include_usage": True})
        payload = self._build_payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            extra=stream_extra,
        )

        try:
            async with client.stream("POST", url, json=payload) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise LLMServiceError(
                        f"LLM 流式调用失败 HTTP {response.status_code}",
                        status_code=response.status_code,
                        detail=body.decode("utf-8", errors="replace"),
                    )
                # OpenAI 兼容 SSE：每行形如 `data: {...}`，结束标记为 `data: [DONE]`
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if line.startswith(":"):
                        # 注释行 / keepalive，忽略
                        continue
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if not data_str or data_str == "[DONE]":
                        if data_str == "[DONE]":
                            break
                        continue
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        logger.warning("LLM 流式块 JSON 解析失败: %s", data_str[:200])
                        continue
                    if usage_sink is not None:
                        usage = chunk.get("usage")
                        if isinstance(usage, dict) and usage:
                            usage_sink.update(usage)
                    delta = self._extract_delta_content(chunk)
                    if delta:
                        # 保留模型附带的推理标签，由前端与最终回答分开展示，便于用户查看过程。
                        yield delta
        except LLMServiceError:
            raise
        except httpx.TimeoutException as exc:
            raise LLMServiceError(f"LLM 流式请求超时（>{self.timeout_seconds}s）") from exc
        except httpx.HTTPError as exc:
            raise LLMServiceError(f"LLM 流式网络错误: {exc}") from exc

    @staticmethod
    def _extract_delta_content(chunk: dict[str, Any]) -> str:
        """从流式 chunk 中提取文本增量，兼容部分厂商字段差异。"""
        try:
            delta = chunk["choices"][0].get("delta") or {}
            content = delta.get("content")
            if content:
                return str(content)
            # 少数兼容实现把文本放在 message.content
            message = chunk["choices"][0].get("message") or {}
            if message.get("content"):
                return str(message["content"])
        except (KeyError, IndexError, TypeError):
            return ""
        return ""

    @staticmethod
    def _safe_error_body(response: httpx.Response) -> Any:
        """尽量解析错误响应体，失败则返回原文截断。"""
        try:
            return response.json()
        except Exception:
            return response.text[:500]


# 模块级单例，供问答编排与摘要模块复用
llm_service = LLMService()

# Guard 和 Query 预处理使用独立的轻量模型客户端。独立连接池可以避免短任务与主回答
# 争用连接；API Key/Base URL 为空时仅复用凭据和地址，不会复用主模型实例。
guard_llm_service = LLMService(
    model=settings.LLM_GUARD_MODEL,
    api_base=settings.LLM_GUARD_BASE_URL,
    api_key=settings.LLM_GUARD_API_KEY,
    timeout_seconds=settings.LLM_GUARD_TIMEOUT_SECONDS,
    default_max_tokens=192,
)
query_processing_llm_service = LLMService(
    model=settings.QA_QUERY_PROCESSING_MODEL,
    api_base=settings.QA_QUERY_PROCESSING_BASE_URL,
    api_key=settings.QA_QUERY_PROCESSING_API_KEY,
    timeout_seconds=settings.QA_QUERY_PROCESSING_TIMEOUT_SECONDS,
    default_max_tokens=settings.QA_QUERY_PROCESSING_MAX_TOKENS,
)

"""用户 Query 预处理服务：改写、扩展与 HyDE 假设文档生成。

设计原则：
1. 三类结果通过一次结构化 LLM 请求生成，减少额外模型调用与响应等待；
2. 任一解析或模型调用异常都安全回退到原始问题，不阻断主问答链路；
3. HyDE 仅作为向量检索的嵌入文本，不会直接展示为最终答案或知识库证据；
4. 输出会写入问答消息的 retrieval_meta，供管理员会话分析页审计。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.query_processing import QueryProcessingConfig
from app.services.llm import LLMServiceError, query_processing_llm_service

logger = logging.getLogger(__name__)

_QUERY_PROCESSING_SYSTEM_PROMPT = """你是企业知识库检索 Query 预处理器。请根据对话历史和最新问题，一次完成以下任务：
1. rewrite：把最新问题改写成可独立理解、适合检索的简短查询，补全指代并保留实体、编号和专业术语；
2. expansions：生成语义相近但关键词不同的检索查询，用于扩大召回；
3. hyde_document：生成一段可能出现在企业知识库中的简短假设答案文档，用于 HyDE 向量检索。

必须只输出一个 JSON 对象，不要输出 Markdown、解释、推理过程或额外文本。格式：
{"rewrite":"...","expansions":["..."],"hyde_document":"..."}

注意：
- rewrite 不超过 80 个字符；
- expansions 不得重复 rewrite 或彼此重复；
- hyde_document 不超过 500 个字符，内容不确定时使用一般性表述，不编造具体制度编号、金额或日期；
- 不回答用户问题，只生成检索辅助文本。"""


def _strip_model_reasoning(text: str) -> str:
    """移除常见推理标签，防止模型内部推理污染检索文本。"""
    cleaned = re.sub(
        r"<(?:redacted_thinking|think|thinking)>[\s\S]*?</(?:redacted_thinking|think|thinking)>",
        "",
        text or "",
        flags=re.IGNORECASE,
    )
    # 兼容上游返回未闭合推理标签的情况，标签之后的内容全部丢弃。
    cleaned = re.sub(
        r"<(?:redacted_thinking|think|thinking)>[\s\S]*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()


def _sanitize_rewrite_output(raw: str, *, fallback: str) -> str:
    """清洗单独的改写结果，保留旧接口测试与降级逻辑兼容性。"""
    text = _strip_model_reasoning(raw or "")
    for prefix in ("改写后的检索查询：", "检索查询：", "查询："):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    lines = [line.strip().strip("\"'`") for line in text.splitlines() if line.strip()]
    candidate = lines[-1] if lines else ""
    # 旧改写接口原本限制 40 字，继续保留该约束，避免破坏既有行为与测试。
    if not candidate or len(candidate) > 40:
        return fallback
    return candidate


@dataclass
class QueryProcessingOptions:
    """一次问答实际使用的 Query 预处理策略。"""

    rewrite_enabled: bool
    expansion_enabled: bool
    expansion_count: int
    hyde_enabled: bool

    @classmethod
    def from_settings(cls) -> QueryProcessingOptions:
        """数据库尚未初始化时使用环境变量中的安全默认值。"""
        return cls(
            rewrite_enabled=settings.QA_QUERY_REWRITE_ENABLED,
            expansion_enabled=settings.QA_QUERY_EXPANSION_ENABLED,
            expansion_count=max(0, min(settings.QA_QUERY_EXPANSION_COUNT, 5)),
            hyde_enabled=settings.QA_HYDE_ENABLED,
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为可落库的审计信息，便于管理员确认当轮实际开关。"""
        return {
            "rewrite_enabled": self.rewrite_enabled,
            "expansion_enabled": self.expansion_enabled,
            "expansion_count": self.expansion_count,
            "hyde_enabled": self.hyde_enabled,
        }


async def ensure_query_processing_config(
    db: AsyncSession,
    *,
    commit: bool = False,
) -> QueryProcessingConfig:
    """幂等创建全局默认配置；默认关闭扩展和 HyDE 以降低问答耗时。"""
    config = await db.scalar(select(QueryProcessingConfig).where(QueryProcessingConfig.config_key == "default"))
    if config is None:
        defaults = QueryProcessingOptions.from_settings()
        config = QueryProcessingConfig(
            config_key="default",
            rewrite_enabled=defaults.rewrite_enabled,
            expansion_enabled=defaults.expansion_enabled,
            expansion_count=defaults.expansion_count,
            hyde_enabled=defaults.hyde_enabled,
        )
        db.add(config)
        if commit:
            await db.commit()
            await db.refresh(config)
        else:
            await db.flush()
    return config


async def get_query_processing_options(db: AsyncSession) -> QueryProcessingOptions:
    """读取管理员策略；异常或缺失时使用环境变量默认值保证问答可用。"""
    config = await db.scalar(select(QueryProcessingConfig).where(QueryProcessingConfig.config_key == "default"))
    if config is None:
        return QueryProcessingOptions.from_settings()
    return QueryProcessingOptions(
        rewrite_enabled=config.rewrite_enabled,
        expansion_enabled=config.expansion_enabled,
        expansion_count=max(0, min(config.expansion_count, 5)),
        hyde_enabled=config.hyde_enabled,
    )


@dataclass
class QueryProcessingResult:
    """一次 Query 预处理的完整、可序列化结果。"""

    original_query: str
    rewritten_query: str
    expanded_queries: list[str] = field(default_factory=list)
    hyde_document: str | None = None
    applied: bool = False
    error: str | None = None
    options: dict[str, Any] = field(default_factory=dict)

    def to_meta(self) -> dict[str, Any]:
        """转换为可安全写入 JSON 字段的管理端展示数据。"""
        return {
            "original_query": self.original_query,
            "rewritten_query": self.rewritten_query,
            "expanded_queries": list(self.expanded_queries),
            "hyde_document": self.hyde_document,
            "applied": self.applied,
            "options": dict(self.options),
            # 仅记录稳定错误码，不保存上游响应正文，避免泄露配置或敏感信息。
            "error": self.error,
        }


class QueryProcessor:
    """调用 LLM 生成 Query 改写、扩展和 HyDE 文档。"""

    async def process(
        self,
        question: str,
        history: list[dict[str, str]],
        *,
        options: QueryProcessingOptions | None = None,
    ) -> QueryProcessingResult:
        """执行预处理；禁用或失败时返回以原问题为主查询的安全结果。"""
        original = (question or "").strip()
        effective_options = options or QueryProcessingOptions.from_settings()
        fallback = QueryProcessingResult(
            original_query=original,
            rewritten_query=original,
            applied=False,
            options=effective_options.to_dict(),
        )
        if not original:
            return fallback
        if not (
            effective_options.rewrite_enabled or effective_options.expansion_enabled or effective_options.hyde_enabled
        ):
            return fallback

        safe_history = self._sanitize_history(history)
        user_payload = {
            "history": safe_history,
            "latest_question": original,
            "expansion_count": effective_options.expansion_count,
            "enabled": {
                "rewrite": effective_options.rewrite_enabled,
                "expansion": effective_options.expansion_enabled,
                "hyde": effective_options.hyde_enabled,
            },
        }
        messages = [
            {"role": "system", "content": _QUERY_PROCESSING_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
            },
        ]

        try:
            # 改写、扩展和 HyDE 共用一次结构化调用，但由独立轻量模型处理，
            # 不再让主回答模型串行承担预处理工作。
            raw = await query_processing_llm_service.chat(
                messages,
                temperature=0.1,
                max_tokens=settings.QA_QUERY_PROCESSING_MAX_TOKENS,
            )
            parsed = self._parse_json_object(raw)
            return self._build_result(original, parsed, effective_options)
        except LLMServiceError as exc:
            logger.warning("Query 预处理模型调用失败，回退原问题：%s", exc)
            fallback.error = "llm_unavailable"
            return fallback
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Query 预处理结果解析失败，回退原问题：%s", exc)
            fallback.error = "invalid_model_output"
            return fallback

    @staticmethod
    def _sanitize_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
        """清洗最近三轮历史，限制长度并移除模型推理标签。"""
        safe_history: list[dict[str, str]] = []
        for message in history[-6:]:
            role = str(message.get("role") or "user")
            if role not in {"user", "assistant"}:
                continue
            content = _strip_model_reasoning(str(message.get("content") or ""))
            if not content:
                continue
            # 助手长回答只保留前 300 字，控制结构化请求大小并降低跑题概率。
            limit = 300 if role == "assistant" else 500
            safe_history.append({"role": role, "content": content[:limit]})
        return safe_history

    @staticmethod
    def _parse_json_object(raw: str) -> dict[str, Any]:
        """兼容纯 JSON、Markdown 代码块及前后夹带少量文本的返回。"""
        cleaned = _strip_model_reasoning(raw or "").strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            value = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start < 0 or end <= start:
                raise
            value = json.loads(cleaned[start : end + 1])
        if not isinstance(value, dict):
            raise ValueError("Query 预处理结果必须是 JSON 对象")
        return value

    @staticmethod
    def _clean_query(value: Any, *, max_length: int) -> str:
        """把模型字段规范为单行文本，并截断异常过长输出。"""
        if not isinstance(value, str):
            return ""
        cleaned = " ".join(_strip_model_reasoning(value).split()).strip(" \"'`")
        return cleaned[:max_length].strip()

    def _build_result(
        self,
        original: str,
        parsed: dict[str, Any],
        options: QueryProcessingOptions,
    ) -> QueryProcessingResult:
        """按配置开关清洗、去重并构建最终结果。"""
        rewritten = original
        if options.rewrite_enabled:
            candidate = self._clean_query(parsed.get("rewrite"), max_length=80)
            if candidate:
                rewritten = candidate

        expansions: list[str] = []
        raw_expansions = parsed.get("expansions")
        if options.expansion_enabled and isinstance(raw_expansions, list):
            seen = {original.casefold(), rewritten.casefold()}
            limit = options.expansion_count
            for raw_query in raw_expansions:
                query = self._clean_query(raw_query, max_length=100)
                normalized = query.casefold()
                if not query or normalized in seen:
                    continue
                seen.add(normalized)
                expansions.append(query)
                if len(expansions) >= limit:
                    break

        hyde_document: str | None = None
        if options.hyde_enabled:
            candidate = self._clean_query(parsed.get("hyde_document"), max_length=500)
            hyde_document = candidate or None

        return QueryProcessingResult(
            original_query=original,
            rewritten_query=rewritten,
            expanded_queries=expansions,
            hyde_document=hyde_document,
            applied=(rewritten != original or bool(expansions) or bool(hyde_document)),
            options=options.to_dict(),
        )


query_processor = QueryProcessor()

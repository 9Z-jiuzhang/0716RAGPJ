"""会话历史摘要生成：超窗对话压缩为长期记忆。

当 Redis 热上下文超过 QA_CONTEXT_WINDOW 时，将最早若干轮对话
合并进 qa_sessions.summary，并在后续问答中作为 system 级背景注入。

失败策略：摘要调用失败时不阻断主流程，由 session_store 记录错误并保留截断后的上下文。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from app.memory.models import ContextMessage
from app.services.llm import LLMServiceError, llm_service

logger = logging.getLogger(__name__)

_SUMMARY_SYSTEM_PROMPT = """你是对话记忆压缩助手。请根据「已有摘要」和「待压缩的新对话」，输出更新后的简洁摘要。

要求：
1. 使用中文，保留用户关心的关键事实、约束、结论与未决问题；
2. 不要编造对话中不存在的信息；
3. 控制在 300 字以内，条目化或短段落均可；
4. 只输出摘要正文，不要加标题或前缀说明。"""


class ConversationSummarizer:
    """基于 LLM 的多轮对话摘要器。"""

    async def summarize(
        self,
        *,
        existing_summary: str | None,
        messages: Sequence[ContextMessage],
    ) -> str:
        """
        将 overflow 消息合并进长期摘要。

        existing_summary: 已有摘要，可为空
        messages: 需要从热上下文移除、待压缩的消息列表
        """
        if not messages:
            return (existing_summary or "").strip()

        dialog_text = self._format_dialog(messages)
        user_content = self._build_user_prompt(existing_summary, dialog_text)

        try:
            summary = await llm_service.chat(
                messages=[
                    {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.2,
                max_tokens=512,
            )
        except LLMServiceError as exc:
            logger.error("摘要 LLM 调用失败：%s", exc)
            raise

        cleaned = (summary or "").strip()
        if not cleaned:
            # 降级：拼接截断文本，避免丢失全部信息
            return self._fallback_summary(existing_summary, dialog_text)
        return cleaned

    @staticmethod
    def _format_dialog(messages: Sequence[ContextMessage]) -> str:
        """将消息列表格式化为可读对话文本。"""
        lines: list[str] = []
        for msg in messages:
            role_label = {"user": "用户", "assistant": "助手", "system": "系统"}.get(msg.role, msg.role)
            content = (msg.content or "").strip()
            if content:
                lines.append(f"{role_label}：{content}")
        return "\n".join(lines)

    @staticmethod
    def _build_user_prompt(existing_summary: str | None, dialog_text: str) -> str:
        parts: list[str] = []
        if existing_summary and existing_summary.strip():
            parts.append(f"【已有摘要】\n{existing_summary.strip()}")
        parts.append(f"【待压缩的新对话】\n{dialog_text}")
        parts.append("请输出合并后的更新摘要：")
        return "\n\n".join(parts)

    @staticmethod
    def _fallback_summary(existing_summary: str | None, dialog_text: str) -> str:
        """LLM 返回空时的确定性降级摘要。"""
        snippet = dialog_text[:400] + ("..." if len(dialog_text) > 400 else "")
        if existing_summary and existing_summary.strip():
            return f"{existing_summary.strip()}\n{snippet}"
        return snippet


conversation_summarizer = ConversationSummarizer()

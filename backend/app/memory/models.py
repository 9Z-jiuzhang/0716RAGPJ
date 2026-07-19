"""会话热记忆数据结构。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class ContextMessage:
    """单条上下文消息（Redis 热缓存 / LLM 提示共用）。"""

    role: str
    content: str
    message_id: str | None = None
    citations: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.message_id:
            data["message_id"] = self.message_id
        if self.citations:
            data["citations"] = self.citations
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextMessage:
        return cls(
            role=str(data.get("role", "user")),
            content=str(data.get("content", "")),
            message_id=data.get("message_id"),
            citations=data.get("citations"),
        )


@dataclass
class SessionMemory:
    """加载后的会话记忆快照。"""

    session_id: str
    summary: str | None = None
    messages: list[ContextMessage] = field(default_factory=list)
    user_id: str | None = None
    guest_id: str | None = None

    # 单条消息送入 LLM 的最大字符数，防止历史膨胀拖慢生成
    _LLM_MSG_MAX_CHARS: ClassVar[int] = 2000

    @property
    def turn_count(self) -> int:
        """一问一答计为 1 轮。"""
        return len([m for m in self.messages if m.role == "user"])

    @staticmethod
    def _compact_for_llm(content: str) -> str:
        """去掉推理标签并截断过长内容。"""
        text = content or ""
        text = re.sub(
            r"<(?:redacted_thinking|think|thinking)>[\s\S]*?</(?:redacted_thinking|think|thinking)>",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"<(?:redacted_thinking|think|thinking)>[\s\S]*$",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = text.strip()
        limit = SessionMemory._LLM_MSG_MAX_CHARS
        if len(text) > limit:
            return text[:limit] + "…"
        return text

    def to_llm_messages(self) -> list[dict[str, str]]:
        """
        转换为 LLM Chat Completions messages 列表。

        若有长期摘要，注入一条 system 消息；随后拼接最近 N 轮对话。
        """
        out: list[dict[str, str]] = []
        if self.summary and self.summary.strip():
            summary = self._compact_for_llm(self.summary)
            out.append(
                {
                    "role": "system",
                    "content": ("以下是本会话较早轮次的压缩摘要，供理解上下文参考：\n" f"{summary}"),
                }
            )
        for msg in self.messages:
            if msg.role in ("user", "assistant", "system") and msg.content.strip():
                out.append({"role": msg.role, "content": self._compact_for_llm(msg.content)})
        return out

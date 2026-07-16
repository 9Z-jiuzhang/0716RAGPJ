"""
会话与记忆管理包（产品手册 5.6）。

- session_store：Redis 热状态、TTL 续期、用户/访客隔离
- summarizer：超窗对话压缩为长期摘要
- models：SessionMemory / ContextMessage 数据结构
"""

from app.memory.models import ContextMessage, SessionMemory
from app.memory.session_store import SessionAccessError, SessionStore, session_store
from app.memory.summarizer import ConversationSummarizer, conversation_summarizer

__all__ = [
    "ContextMessage",
    "SessionMemory",
    "SessionStore",
    "session_store",
    "SessionAccessError",
    "ConversationSummarizer",
    "conversation_summarizer",
]

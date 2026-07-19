"""会话记忆数据结构单元测试。"""

from app.memory.models import ContextMessage, SessionMemory


def test_session_memory_turn_count() -> None:
    memory = SessionMemory(
        session_id="s1",
        messages=[
            ContextMessage(role="user", content="你好"),
            ContextMessage(role="assistant", content="您好"),
            ContextMessage(role="user", content="再问"),
        ],
    )
    assert memory.turn_count == 2


def test_to_llm_messages_includes_summary() -> None:
    memory = SessionMemory(
        session_id="s1",
        summary="用户之前询问了权限配置。",
        messages=[ContextMessage(role="user", content="继续")],
    )
    msgs = memory.to_llm_messages()
    assert msgs[0]["role"] == "system"
    assert "权限配置" in msgs[0]["content"]
    assert msgs[-1]["content"] == "继续"


def test_to_llm_messages_strips_reasoning_and_truncates() -> None:
    long_body = "答案正文" + ("x" * 3000)
    memory = SessionMemory(
        session_id="s1",
        messages=[
            ContextMessage(
                role="assistant",
                content=f"<think>很长的推理过程</think>\n{long_body}",
            ),
        ],
    )
    msgs = memory.to_llm_messages()
    assert len(msgs) == 1
    assert "很长的推理过程" not in msgs[0]["content"]
    assert msgs[0]["content"].startswith("答案正文")
    assert len(msgs[0]["content"]) <= SessionMemory._LLM_MSG_MAX_CHARS + 1

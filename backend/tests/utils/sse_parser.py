"""SSE 解析：httpx 流式问答 / golden E2E / FAQ 校验复用。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SSEMessage:
    """单条 SSE 事件（event + data 字段解析为 dict 或 str）。"""

    event: str
    data: dict[str, Any] | str | None = None
    raw_data: str = ""


@dataclass
class ParsedSSEStream:
    """一次 ask 请求的完整 SSE 解析结果。"""

    messages: list[SSEMessage] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    chunks: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    retrieval_meta: dict[str, Any] = field(default_factory=dict)
    done_payload: dict[str, Any] = field(default_factory=dict)
    route_payload: dict[str, Any] = field(default_factory=dict)
    tail_events: list[SSEMessage] = field(default_factory=list)

    @property
    def answer_text(self) -> str:
        return "".join(self.chunks)

    def had_event(self, name: str) -> bool:
        return name in self.events


def parse_sse_chunk(buffer: str) -> tuple[list[SSEMessage], str]:
    """
    从 buffer 解析完整 SSE 消息（以空行分隔），返回 (messages, remainder)。
    支持 event / data 多行 data 拼接。
    """
    messages: list[SSEMessage] = []
    if not buffer:
        return messages, ""

    parts = buffer.split("\n\n")
    remainder = ""
    if not buffer.endswith("\n\n") and parts:
        remainder = parts.pop()

    for block in parts:
        block = block.strip("\r")
        if not block.strip():
            continue
        event_name = "message"
        data_lines: list[str] = []
        for line in block.split("\n"):
            line = line.strip("\r")
            if not line or line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())

        raw_data = "\n".join(data_lines)
        parsed: dict[str, Any] | str | None = None
        if raw_data:
            try:
                parsed = json.loads(raw_data)
            except json.JSONDecodeError:
                parsed = raw_data

        messages.append(SSEMessage(event=event_name, data=parsed, raw_data=raw_data))

    return messages, remainder


def fold_sse_messages(messages: list[SSEMessage]) -> ParsedSSEStream:
    """将 SSE 消息列表折叠为结构化结果（处理 done 后尾事件）。"""
    out = ParsedSSEStream()
    done_index: int | None = None

    for i, msg in enumerate(messages):
        out.messages.append(msg)
        out.events.append(msg.event)

        data = msg.data if isinstance(msg.data, dict) else {}

        if msg.event == "chunk":
            content = data.get("content") or data.get("text") or ""
            if content:
                out.chunks.append(str(content))
        elif msg.event == "citations":
            cites = data.get("citations")
            if isinstance(cites, list):
                out.citations = cites
            items = data.get("items")
            if isinstance(items, list):
                out.citations = items
        elif msg.event == "route":
            out.route_payload = data
        elif msg.event == "done":
            done_index = i
            out.done_payload = data
            meta = data.get("retrieval_meta")
            if isinstance(meta, dict):
                out.retrieval_meta = meta

    if done_index is not None and done_index + 1 < len(messages):
        out.tail_events = messages[done_index + 1:]

    if not out.retrieval_meta and isinstance(out.done_payload.get("retrieval_meta"), dict):
        out.retrieval_meta = out.done_payload["retrieval_meta"]

    return out


async def consume_sse_stream(line_iter: Any) -> ParsedSSEStream:
    """从 httpx aiter_lines() 迭代器消费并解析完整 SSE 流。"""
    buffer = ""
    all_messages: list[SSEMessage] = []

    async for line in line_iter:
        if line is None:
            continue
        buffer += line + "\n"
        if buffer.endswith("\n\n") or buffer.endswith("\r\n\r\n"):
            msgs, buffer = parse_sse_chunk(buffer)
            all_messages.extend(msgs)

    if buffer.strip():
        msgs, _ = parse_sse_chunk(buffer + "\n\n")
        all_messages.extend(msgs)

    return fold_sse_messages(all_messages)

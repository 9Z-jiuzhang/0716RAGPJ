"""文本规范化与预处理。【对齐手册 §5.5.1 / §5.5.2】"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class NormalizeStats:
    removed_blank_lines: int = 0
    removed_duplicate_blocks: int = 0
    char_count_before: int = 0
    char_count_after: int = 0


def normalize_text(text: str) -> tuple[str, NormalizeStats]:
    """去除多余空白/换行、统一编码感、过滤空段，保留标题层级标记。"""
    stats = NormalizeStats(char_count_before=len(text))
    # 统一换行
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 去掉行尾空白
    lines = [line.rstrip() for line in text.split("\n")]
    # 压缩连续空行
    compact: list[str] = []
    blank_streak = 0
    for line in lines:
        if not line.strip():
            blank_streak += 1
            if blank_streak == 1:
                compact.append("")
            else:
                stats.removed_blank_lines += 1
            continue
        blank_streak = 0
        # 压缩行内多空格（保留 markdown 标题前缀）
        if re.match(r"^#{1,6}\s", line):
            compact.append(line)
        else:
            compact.append(re.sub(r"[ \t]{2,}", " ", line))
    # 去重连续相同非空块
    deduped: list[str] = []
    prev = None
    for line in compact:
        if line and line == prev:
            stats.removed_duplicate_blocks += 1
            continue
        deduped.append(line)
        prev = line if line else None
    result = "\n".join(deduped).strip() + ("\n" if deduped else "")
    stats.char_count_after = len(result)
    return result, stats

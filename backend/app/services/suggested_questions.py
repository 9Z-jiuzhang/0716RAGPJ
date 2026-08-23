"""问答 SSE 尾事件：推荐追问（启发式 A+D，无额外 LLM）。"""

from __future__ import annotations

import re
from typing import Any

from app.core.config import settings

_MAX = 3

# A：识别上一轮推荐问/用户点选的模板句，剥出「」内核心主题
_TEMPLATE_PATTERNS = [
    re.compile(r"除了「[^」]+」，?还有哪些值得关注的背景信息？"),
    re.compile(r"「[^」]+」还有哪些与「[^」]+」相关的要点？"),
    re.compile(r"「[^」]+」表格里的关键数据能否再解释一下？"),
    re.compile(r"「[^」]+」在知识库中还有哪些补充说明？"),
    re.compile(r"「[^」]+」中关于「[^」]+」的更多细节？"),
    re.compile(r"「[^」]+」表格的关键数据如何解读？"),
    re.compile(r"「[^」]+」具体指什么？"),
    re.compile(r"「[^」]+」具体含义？"),
    re.compile(r"「[^」]+」的背景与意义？"),
    re.compile(r"「[^」]+」有哪些关键变化？"),
    re.compile(r"「[^」]+」数据来源是什么？"),
    re.compile(r"「[^」]+」在知识库中如何定义？"),
    re.compile(r"「[^」]+」上下游关系？"),
]

# D：按实体类型生成追问（实体用「」包裹，避免模板残片被再次抽词）
_ENTITY_TEMPLATES: dict[str, list[str]] = {
    "year": ["「{e}」有哪些关键变化？", "「{e}」的背景与意义？"],
    "number": ["「{e}」数据来源是什么？", "「{e}」如何解读？"],
    "term": ["「{e}」具体指什么？", "「{e}」与上下游关系？"],
}

_YEAR_RE = re.compile(r"(20\d{2})年")
_NUMBER_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(亿|万|%|纳米|nm|个|家|元|美元|人民币)"
)
_TERM_RE = re.compile(r"[\u4e00-\u9fff]{4,10}")
_CJK_WORD_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_HTML_TAG_RE = re.compile(r"<[^>]+>")

# 模型/RAG 套话、推荐问模板残片 — 禁止作为实体
_META_TERM_BLOCKLIST = frozenset(
    {
        "用户询问",
        "用户问题",
        "检索证据",
        "检索证据中",
        "检索依据",
        "本轮检索",
        "依据不足",
        "对话历史",
        "引用来源",
        "会话延续",
        "企业知识库",
        "知识库",
        "智能问答",
        "问答助手",
        "在知识库中如何定义",
        "在知识库中",
        "如何定义",
        "如何计算",
        "详细解释",
        "上下游关系",
        "背景与意义",
        "行业情况",
        "数据来源是什么",
        "具体指什么",
        "具体含义",
        "关键变化",
        "如何解读",
    }
)

_META_SUBSTRINGS = (
    "检索证据",
    "检索依据",
    "用户询问",
    "用户问题",
    "知识库中如何",
    "在知识库",
    "依据不足",
    "对话历史",
    "引用来源",
    "会话延续",
    "如何定义",
    "如何计算",
    "详细解释",
)


def suggested_questions_enabled() -> bool:
    return bool(settings.SUGGESTED_QUESTIONS_ENABLED)


def _strip_template(question: str) -> str:
    """剥掉模板外壳，只留核心主题。"""
    text = (question or "").strip()
    for pat in _TEMPLATE_PATTERNS:
        if pat.search(text):
            inner = re.findall(r"「([^」]+)」", text)
            if inner:
                return inner[0].strip()
            return re.sub(pat, "", text).strip()
    # 无书名号但整句像点过的推荐问
    if text.endswith("？") and any(s in text for s in ("如何定义", "具体指什么", "数据来源")):
        return ""
    return text


def _is_repetitive(new_q: str, current_q: str) -> bool:
    """new_q 与 current_q 相同/互为子串/核心词重叠过高 → 拒绝。"""
    if not new_q or not current_q:
        return False
    if new_q == current_q or new_q in current_q or current_q in new_q:
        return True
    new_words = set(_CJK_WORD_RE.findall(new_q))
    cur_words = set(_CJK_WORD_RE.findall(current_q))
    if new_words and cur_words:
        overlap = len(new_words & cur_words) / max(len(new_words), len(cur_words))
        if overlap > 0.7:
            return True
    return False


def _is_bad_entity(token: str) -> bool:
    text = (token or "").strip()
    if len(text) < 4:
        return True
    if text in _META_TERM_BLOCKLIST:
        return True
    if any(sub in text for sub in _META_SUBSTRINGS):
        return True
    # 整句几乎都是模板词
    if all(ch in "在知识库中如何定义计算解释上下游关系背景意义行业情况数据来源具体指什么关键变化解读" for ch in text):
        return True
    return False


def _is_valid_theme(theme: str) -> bool:
    text = (theme or "").strip()
    if len(text) < 4 or len(text) > 48:
        return False
    if _is_bad_entity(text):
        return False
    return True


def _citation_corpus(citations: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for cite in citations or []:
        raw = str(cite.get("content") or "")
        if not raw.strip():
            continue
        plain = _HTML_TAG_RE.sub(" ", raw)
        plain = re.sub(r"\s+", " ", plain).strip()
        if plain:
            parts.append(plain)
    return "\n".join(parts)


def _extract_entities(
    answer: str,
    citations: list[dict[str, Any]],
    max_n: int = 8,
) -> list[dict[str, str]]:
    """年份/数字从回答正文；术语只从引用片段抽，避免模型套话。"""
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(text: str, kind: str) -> None:
        token = (text or "").strip()
        if not token or token in seen or len(token) > 16:
            return
        if _is_bad_entity(token):
            return
        seen.add(token)
        out.append({"text": token, "kind": kind})

    answer_text = (answer or "").strip()
    for m in _YEAR_RE.finditer(answer_text):
        _add(m.group(0), "year")

    for m in _NUMBER_RE.finditer(answer_text):
        _add(m.group(0), "number")

    # 术语：仅扫描引用原文（证据段），不扫模型自述
    corpus = _citation_corpus(citations)
    for m in _TERM_RE.finditer(corpus):
        _add(m.group(0), "term")
        if len(out) >= max_n:
            break

    return out[:max_n]


def build_suggested_questions(
    *,
    question: str,
    answer: str,
    citations: list[dict[str, Any]],
) -> list[str]:
    """基于引用片段实体（D）+ 引用文档（A 去套娃）生成最多 3 条追问。"""
    if not suggested_questions_enabled():
        return []

    out: list[str] = []
    seen: set[str] = set()
    core = _strip_template(question)
    raw_question = (question or "").strip()

    def _add(q: str) -> None:
        text = (q or "").strip()
        if not text or text in seen or len(text) > 120:
            return
        if _is_repetitive(text, raw_question) or _is_repetitive(text, core):
            return
        # 生成句本身含套话 → 丢弃
        inner = re.findall(r"「([^」]+)」", text)
        if inner and any(_is_bad_entity(part) for part in inner):
            return
        seen.add(text)
        out.append(text)

    for ent in _extract_entities(answer, citations):
        templates = _ENTITY_TEMPLATES.get(ent["kind"], ["「{e}」具体指什么？"])
        _add(templates[0].format(e=ent["text"]))
        if len(out) >= _MAX:
            return out[:_MAX]

    theme = core if _is_valid_theme(core) else ""
    for cite in citations or []:
        doc = (cite.get("doc_name") or "").strip()
        if not doc:
            continue
        if theme:
            _add(f"「{doc}」中关于「{theme[:24]}」的更多细节？")
        else:
            _add(f"「{doc}」还有哪些值得了解的要点？")
        if cite.get("block_type") == "table":
            _add(f"「{doc}」表格的关键数据如何解读？")
        if len(out) >= _MAX:
            return out[:_MAX]

    return out[:_MAX]

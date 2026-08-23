"""业务意图路由：Guard 之后决定是否进知识库 / 使用上一答案。"""

from __future__ import annotations

import logging
import re

from app.schemas.optimization_contracts import ConversationIntent, ConversationRouteDecision

logger = logging.getLogger(__name__)

_GREETING = re.compile(
    r"^(你好|您好|嗨|哈喽|hello|hi|hey|早上好|下午好|晚上好|在吗)[\s!！。.~～？?]*$",
    re.IGNORECASE,
)
_THANKS = re.compile(
    r"^(谢谢|多谢|感谢|拜拜|再见|thanks|thank\s*you|bye|goodbye)[\s!！。.~～]*$",
    re.IGNORECASE,
)
# 能力说明 / 怎么用（不展开内部实现）
_SYSTEM_HELP = re.compile(
    r"(怎么用|如何使用|有什么功能|有哪些功能|帮助|使用说明|你可以做什么|能做什么|"
    r"你是谁|你是什么|你会什么|能力介绍|使用帮助)",
    re.IGNORECASE,
)
# 系统运行机制 / 内部架构 / RAG 自述（硬拦，不进检索）
_SYSTEM_MECHANISM = re.compile(
    r"(怎么运行|如何运行|如何工作|怎样工作|工作原理|运行机制|运行方式|"
    r"系统架构|内部实现|实现原理|技术架构|底层(是)?怎么|"
    r"提示词|system\s*prompt|模型参数|用的什么模型|什么大模型|"
    r"检索链路|检索流程|向量(库|检索)|RAG\s*原理|rag\s*原理|"
    r"你们?系统是怎么|这个系统是怎么|助手是怎么(运行|工作))",
    re.IGNORECASE,
)
_TRANSFORM = re.compile(
    r"(简略|简洁|精简|概括|总结|三句话|表格|翻译成|换成英文|改成英文|更短一点|长一点|详细一点)",
    re.IGNORECASE,
)
_FOLLOWUP = re.compile(
    r"(第[一二三四五六七八九十\d]+|上面|刚才|它|这个|那个|例外|什么时候生效|继续)",
    re.IGNORECASE,
)
_OUT_OF_SCOPE = re.compile(
    r"(帮我写代码|炒股|恋爱|算命|生成图片|下载电影|写小说|游戏攻略|写诗|作诗|讲笑话|" r"恋爱文案|情书|星座运势)",
    re.IGNORECASE,
)
_VAGUE_KB_QUERY = re.compile(
    r"(那个|这个|啥|什么|哪种|哪家).{0,24}(政策|规定|制度|流程|方案|计划|补贴|扶持).{0,12}(怎么样|如何|咋样|怎样|到底)",
    re.IGNORECASE,
)

# 未命中时允许 LLM 参考答案的意图白名单（开关开启时仍生效）
FALLBACK_LLM_ALLOWED_INTENTS = frozenset(
    {
        ConversationIntent.NEW_KB_QUERY,
        ConversationIntent.CONTEXT_FOLLOWUP_KB,
        ConversationIntent.ROUTE_FALLBACK,
    }
)


def _transform_type(question: str) -> str:
    q = question or ""
    if re.search(r"表格", q):
        return "table"
    if re.search(r"翻译|英文", q):
        return "translate"
    if re.search(r"详细", q):
        return "expand"
    if re.search(r"三句话|概括|总结", q):
        return "summarize"
    return "shorten"


class ConversationRouter:
    """高精度规则优先；低置信度时默认进入知识库查询，避免误判闲聊。"""

    version = "rules-v2"

    def route(
        self,
        *,
        question: str,
        has_last_answer: bool,
        history_turns: int = 0,
        observe_only: bool = False,
        clarify_enabled: bool = True,
    ) -> ConversationRouteDecision:
        text = (question or "").strip()
        if not text:
            return ConversationRouteDecision(
                intent=ConversationIntent.CLARIFICATION,
                confidence=1.0,
                should_clarify=True,
                reason_code="empty_question",
                classifier_version=self.version,
            )

        if _GREETING.match(text):
            return ConversationRouteDecision(
                intent=ConversationIntent.GREETING_CHAT,
                confidence=0.99,
                reason_code="greeting_rule",
                classifier_version=self.version,
            )
        if _THANKS.match(text):
            return ConversationRouteDecision(
                intent=ConversationIntent.THANKS_GOODBYE,
                confidence=0.99,
                reason_code="thanks_rule",
                classifier_version=self.version,
            )
        # 机制类优先于帮助类，避免「怎么运行」被宽泛帮助规则误吸
        if _SYSTEM_MECHANISM.search(text):
            return ConversationRouteDecision(
                intent=ConversationIntent.SYSTEM_MECHANISM,
                confidence=0.92,
                should_retrieve=False,
                reason_code="system_mechanism_rule",
                classifier_version=self.version,
            )
        if _SYSTEM_HELP.search(text) and len(text) < 80:
            return ConversationRouteDecision(
                intent=ConversationIntent.SYSTEM_HELP,
                confidence=0.9,
                reason_code="system_help_rule",
                classifier_version=self.version,
            )
        if _OUT_OF_SCOPE.search(text):
            return ConversationRouteDecision(
                intent=ConversationIntent.OUT_OF_SCOPE,
                confidence=0.85,
                reason_code="oos_rule",
                classifier_version=self.version,
            )
        if clarify_enabled and _VAGUE_KB_QUERY.search(text):
            return ConversationRouteDecision(
                intent=ConversationIntent.CLARIFICATION,
                confidence=0.88,
                should_clarify=True,
                should_retrieve=False,
                reason_code="vague_kb_query",
                classifier_version=self.version,
            )
        if _TRANSFORM.search(text) and has_last_answer:
            return ConversationRouteDecision(
                intent=ConversationIntent.PREVIOUS_ANSWER_TRANSFORM,
                confidence=0.95,
                should_use_last_answer=True,
                reason_code="transform_rule",
                transform_type=_transform_type(text),
                classifier_version=self.version,
            )
        if _TRANSFORM.search(text) and not has_last_answer:
            if clarify_enabled:
                return ConversationRouteDecision(
                    intent=ConversationIntent.CLARIFICATION,
                    confidence=0.9,
                    should_clarify=True,
                    reason_code="transform_without_context",
                    classifier_version=self.version,
                )
        if history_turns > 0 and _FOLLOWUP.search(text):
            return ConversationRouteDecision(
                intent=ConversationIntent.CONTEXT_FOLLOWUP_KB,
                confidence=0.8,
                should_retrieve=True,
                normalized_query=text,
                reason_code="followup_rule",
                classifier_version=self.version,
            )

        decision = ConversationRouteDecision(
            intent=ConversationIntent.NEW_KB_QUERY,
            confidence=0.75,
            should_retrieve=True,
            normalized_query=text,
            reason_code="default_kb",
            classifier_version=self.version,
        )
        if observe_only:
            logger.info(
                "route observe intent=%s reason=%s q_len=%s",
                decision.intent.value,
                decision.reason_code,
                len(text),
            )
        return decision

    def template_reply(self, decision: ConversationRouteDecision) -> str | None:
        """非知识库路径的模板回答。"""
        if decision.intent == ConversationIntent.GREETING_CHAT:
            return "您好，我是企业知识库助手。请直接提出业务问题，我会基于已授权知识库为您检索作答。"
        if decision.intent == ConversationIntent.THANKS_GOODBYE:
            return "不客气。如还有问题，随时继续提问。"
        if decision.intent == ConversationIntent.SYSTEM_HELP:
            return (
                "我可以基于您有权限的知识库回答制度、流程与产品问题，"
                "支持多轮追问，也可以请我将上一回答改得更简略或整理成表格。"
                "我不会把知识库未命中的内容伪装成企业正式依据。"
            )
        if decision.intent == ConversationIntent.SYSTEM_MECHANISM:
            return (
                "我是企业知识库问答助手，仅基于您有权限的知识库文档作答，"
                "不会展开本系统的内部实现、架构或模型配置细节。"
                "运行机制与技术说明请以企业内部正式文档为准；"
                "如需办理业务，请直接提问相关制度或流程。"
            )
        if decision.intent == ConversationIntent.OUT_OF_SCOPE:
            return "该请求超出企业知识库助手的能力范围。请提出与企业知识库相关的问题。"
        if decision.intent == ConversationIntent.CLARIFICATION and decision.reason_code == "transform_without_context":
            return "当前会话还没有可变换的上一回答。请先提出一个知识库问题，或说明您希望改写的具体内容。"
        if decision.intent == ConversationIntent.CLARIFICATION and decision.reason_code == "vague_kb_query":
            return (
                "您的问题指向不够具体，难以在知识库中准确检索。"
                "请补充政策/制度名称、关注的时间范围或业务场景（例如国家扶持、地方补贴或企业内部制度），"
                "我再为您检索作答。"
            )
        return None

    def transform_answer(self, *, last_answer: str, transform_type: str | None) -> str:
        """基于上一答案做轻量变换，不引入新事实。"""
        text = (last_answer or "").strip()
        if not text:
            return "上一回答为空，无法变换。请先进行一轮知识库问答。"
        t = transform_type or "shorten"
        if t == "table":
            lines = [ln.strip(" -•\t") for ln in text.splitlines() if ln.strip()]
            rows = lines[:8] or [text[:200]]
            body = "\n".join(f"| {i + 1} | {row[:120]} |" for i, row in enumerate(rows))
            return f"根据上一回答整理（未新增事实）：\n\n| 序号 | 要点 |\n| --- | --- |\n{body}"
        if t == "translate":
            return (
                "以下为上一回答的英文转述（内容仍仅来自上一回答，未新增事实）：\n\n"
                f"{text}\n\n"
                "(English paraphrase placeholder: content equivalent to the Chinese answer above.)"
            )
        if t == "expand":
            return f"在不新增事实的前提下，将上一回答展开表述如下：\n\n{text}"
        # shorten / summarize
        # 编号列表中的“1.”、“2.”不是句号。优先以列表项为单位截取，既保留编号也避免截断条目正文。
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        number_item_re = re.compile(r"^(?:[-*•]\s+|(?:\d+|[一二三四五六七八九十]+)[.、)]\s*)")
        numbered_indexes = [idx for idx, line in enumerate(lines) if number_item_re.match(line)]
        if len(numbered_indexes) >= 2:
            # 保留列表前的简短引导语，并仅返回前三个完整列表项。
            first_index = numbered_indexes[0]
            prefix = lines[:first_index]
            selected = lines[numbered_indexes[0] : numbered_indexes[3]]
            short = "\n".join([*prefix, *selected]).strip()
        else:
            # 英文句号只有在前一字符不是数字、后一段以大写英文或中文起始时才视为句末。
            # 这样“1. 上班时间”不会被错误拆成“1.”和“上班时间”。
            sentences = re.split(
                r"(?<=[。！？!?])\s*|(?<!\d)(?<=[.])(?=\s+(?:[A-Z\u4e00-\u9fff]))",
                text,
            )
            sentences = [sentence.strip() for sentence in sentences if sentence.strip()]
            # 分句结果已保留原有标点，不能再额外拼接句号，以免出现“。。”。
            short = "\n".join(sentences[:3])
        if short and not short.endswith(("。", "！", "？", ".", "!", "?")):
            short += "。"
        return f"简要版（仅基于上一回答）：\n\n{short or text[:300]}"


conversation_router = ConversationRouter()

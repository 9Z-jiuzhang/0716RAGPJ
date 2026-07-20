"""问答用户可见语言策略测试。"""

from app.core.qa_pipeline import _RAG_SYSTEM_PROMPT, _REFERENCE_SYSTEM_PROMPT


def test_all_user_visible_answer_prompts_require_simplified_chinese() -> None:
    """主回答和无命中参考回答都必须要求最终答案和推理过程使用简体中文。"""
    for prompt in (_RAG_SYSTEM_PROMPT, _REFERENCE_SYSTEM_PROMPT):
        assert "仅使用简体中文" in prompt
        assert "推理与最终回答都必须使用简体中文" in prompt

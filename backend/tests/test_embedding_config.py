"""Embedding 配置校验测试。

测试只使用虚拟密钥，不读取开发机真实环境变量，确保错误信息中不会泄露敏感配置。
"""

from __future__ import annotations

import pytest
from app.services.embedding import EmbeddingServiceError, _resolve_embedding_api_key


def test_embedding_key_rejects_non_ascii_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    """中文占位内容必须在创建 HTTP 客户端前被识别并返回明确错误。"""
    monkeypatch.setattr("app.services.embedding.settings.EMBEDDING_API_KEY", "这里填写密钥")
    monkeypatch.setattr("app.services.embedding.settings.LLM_API_KEY", "")

    with pytest.raises(EmbeddingServiceError, match="未配置有效密钥|非 ASCII"):
        _resolve_embedding_api_key()


def test_embedding_key_rejects_ascii_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    """常见英文占位值也不能被误认为可调用的生产密钥。"""
    monkeypatch.setattr("app.services.embedding.settings.EMBEDDING_API_KEY", "change-me")
    monkeypatch.setattr("app.services.embedding.settings.LLM_API_KEY", "")

    with pytest.raises(EmbeddingServiceError, match="未配置有效密钥"):
        _resolve_embedding_api_key()


def test_embedding_key_accepts_valid_ascii_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """合法 ASCII 密钥原样返回，后续客户端可以安全放入 Authorization 请求头。"""
    monkeypatch.setattr("app.services.embedding.settings.EMBEDDING_API_KEY", "sk-test-valid-key")
    monkeypatch.setattr("app.services.embedding.settings.LLM_API_KEY", "")

    assert _resolve_embedding_api_key() == "sk-test-valid-key"

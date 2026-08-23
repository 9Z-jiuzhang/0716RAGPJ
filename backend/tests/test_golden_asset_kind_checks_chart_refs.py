"""Golden E2E 辅助：_citation_has_chart_kind 契约（chart_refs 优先，images fallback）。"""

from tests.test_golden_e2e import _citation_has_chart_kind


def test_citation_has_chart_kind_from_chart_refs() -> None:
    assert _citation_has_chart_kind(
        [{"chart_refs": [{"kind": "asset", "asset_id": "abc12345"}], "images": []}],
        "asset",
    )


def test_citation_has_chart_kind_from_legacy_images() -> None:
    assert _citation_has_chart_kind(
        [{"chart_refs": [], "images": [{"kind": "asset"}]}],
        "asset",
    )


def test_citation_has_chart_kind_false_when_empty() -> None:
    assert not _citation_has_chart_kind([{"chart_refs": [], "images": []}], "asset")

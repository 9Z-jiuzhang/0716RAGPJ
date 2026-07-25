"""访问控制相关常量与派生助手。

整合“可见性(visibility)”与“部门(department)”：
- 部门是唯一的访问控制轴；一个知识库可关联多个部门；
- 固定的“访客专用”部门（code=GUEST）代替原先的 public 可见性，
  关联 GUEST 的知识库对所有人（访客/员工/管理员）可见；
- visibility 字段保留但由部门列表派生（含 GUEST -> public，其余 -> restricted），
  仅用于展示与向后兼容。
"""

from __future__ import annotations

from collections.abc import Iterable

# 固定“访客专用”部门
GUEST_DEPARTMENT_CODE = "GUEST"
GUEST_DEPARTMENT_NAME = "访客专用"
GUEST_DEPARTMENT_DESC = "访客可访问的公开知识库集合；员工与管理员同样可访问。"

VISIBILITY_PUBLIC = "public"
VISIBILITY_RESTRICTED = "restricted"


def normalize_department(code: str | None) -> str | None:
    """规范化部门编码：去空白、转大写；空值返回 None。"""
    cleaned = (code or "").strip().upper()
    return cleaned or None


def normalize_departments(codes: Iterable[str] | None) -> list[str]:
    """规范化并去重部门编码列表，保持稳定排序（GUEST 优先）。"""
    seen: set[str] = set()
    out: list[str] = []
    for raw in codes or []:
        code = normalize_department(raw)
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    out.sort(key=lambda c: (0 if c == GUEST_DEPARTMENT_CODE else 1, c))
    return out


def is_guest_department(code: str | None) -> bool:
    """是否为“访客专用”部门。"""
    return normalize_department(code) == GUEST_DEPARTMENT_CODE


def primary_department(codes: Iterable[str] | None) -> str | None:
    """兼容列首选部门：含 GUEST 则取 GUEST，否则取排序后首个。"""
    normalized = normalize_departments(codes)
    return normalized[0] if normalized else None


def derive_visibility(department: str | None) -> str:
    """由单部门派生可见性（兼容旧调用）。"""
    return VISIBILITY_PUBLIC if is_guest_department(department) else VISIBILITY_RESTRICTED


def derive_visibility_from_departments(codes: Iterable[str] | None) -> str:
    """由多部门派生可见性：任一为 GUEST → public，否则 restricted。"""
    for code in codes or []:
        if is_guest_department(code):
            return VISIBILITY_PUBLIC
    return VISIBILITY_RESTRICTED

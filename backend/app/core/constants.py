"""访问控制相关常量与派生助手。

整合“可见性(visibility)”与“部门(department)”：
- 部门是唯一的访问控制轴；
- 固定的“访客专用”部门（code=GUEST）代替原先的 public 可见性，
  归属该部门的知识库对所有人（访客/员工/管理员）可见；
- visibility 字段保留但由部门派生（GUEST -> public，其余 -> restricted），
  仅用于展示与向后兼容。
"""

from __future__ import annotations

from typing import Optional

# 固定“访客专用”部门
GUEST_DEPARTMENT_CODE = "GUEST"
GUEST_DEPARTMENT_NAME = "访客专用"
GUEST_DEPARTMENT_DESC = "访客可访问的公开知识库集合；员工与管理员同样可访问。"

VISIBILITY_PUBLIC = "public"
VISIBILITY_RESTRICTED = "restricted"


def normalize_department(code: Optional[str]) -> Optional[str]:
    """规范化部门编码：去空白、转大写；空值返回 None。"""
    cleaned = (code or "").strip().upper()
    return cleaned or None


def is_guest_department(code: Optional[str]) -> bool:
    """是否为“访客专用”部门。"""
    return normalize_department(code) == GUEST_DEPARTMENT_CODE


def derive_visibility(department: Optional[str]) -> str:
    """由部门派生可见性：访客专用 -> public，其余 -> restricted。"""
    return VISIBILITY_PUBLIC if is_guest_department(department) else VISIBILITY_RESTRICTED

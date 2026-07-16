"""工具函数。"""

from uuid import uuid4


def new_request_id() -> str:
    """生成请求标识。"""
    return str(uuid4())

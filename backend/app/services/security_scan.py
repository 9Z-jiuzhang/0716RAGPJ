"""安全校验：启发式恶意内容检测 + 可选 ClamAV。"""

from __future__ import annotations

import logging
import re
import socket

from app.core.config import settings
from app.utils.exceptions import DocumentError

logger = logging.getLogger(__name__)

_EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class MalwareDetectedError(DocumentError):
    def __init__(self, reason: str):
        super().__init__(f"安全扫描未通过: {reason}", http_status=400)


def virus_scan(filename: str, content: bytes) -> None:
    """
    上传前安全扫描。

    1) 始终执行启发式检测（EICAR / 可执行头 / 脚本）
    2) 若 VIRUS_SCAN_ENABLED，再走 ClamAV clamd INSTREAM
    """
    if content is None:
        raise DocumentError("空文件不可上传", http_status=400)

    _heuristic_scan(filename, content)

    if settings.VIRUS_SCAN_ENABLED:
        _clamav_scan(filename, content)

    logger.info("virus_scan ok file=%s size=%s", filename, len(content))


def virus_scan_placeholder(filename: str, content: bytes) -> None:
    """兼容旧调用名。"""
    virus_scan(filename, content)


def validate_encoding_safe(content: bytes) -> None:
    """基础编码探测：空文件拒绝。"""
    if content is None or len(content) == 0:
        raise ValueError("空文件不可上传")


def _heuristic_scan(filename: str, content: bytes) -> None:
    lower_name = (filename or "").lower()
    ext = lower_name.rsplit(".", 1)[-1] if "." in lower_name else ""
    text_like = ext in {"txt", "md", "markdown", "csv", "json", "xml", "html", "htm"}
    office_like = ext in {"doc", "docx", "xls", "xlsx", "ppt", "pptx", "pdf"}

    if _EICAR in content:
        raise MalwareDetectedError("检测到 EICAR 测试病毒特征")

    head = content[:8]
    if head.startswith(b"MZ") and not office_like:
        raise MalwareDetectedError("疑似 Windows PE 可执行文件")
    if head.startswith(b"\x7fELF"):
        raise MalwareDetectedError("疑似 ELF 可执行文件")
    if text_like and content.lstrip().startswith(b"#!/"):
        raise MalwareDetectedError("文本扩展名下检测到脚本 shebang")

    sample = content[:64 * 1024]
    if re.search(br"(?i)<script[\s>]", sample) and ext not in {"html", "htm", "xml"}:
        raise MalwareDetectedError("疑似嵌入脚本")
    if re.search(br"(?i)AutoOpen|Auto_Open|Document_Open", sample) and not office_like:
        raise MalwareDetectedError("疑似自动宏触发")


def _clamav_scan(filename: str, content: bytes) -> None:
    host = settings.CLAMAV_HOST
    port = int(settings.CLAMAV_PORT)
    try:
        with socket.create_connection((host, port), timeout=5) as sock:
            sock.sendall(b"zINSTREAM\0")
            chunk_size = 2048
            for i in range(0, len(content), chunk_size):
                chunk = content[i : i + chunk_size]
                sock.sendall(len(chunk).to_bytes(4, "big") + chunk)
            sock.sendall((0).to_bytes(4, "big"))
            resp = sock.recv(4096).decode("utf-8", errors="replace").strip()
    except OSError as exc:
        logger.warning("ClamAV 不可用，跳过引擎扫描: %s", exc)
        return

    if "FOUND" in resp:
        raise MalwareDetectedError(f"ClamAV 检出: {resp}")
    if "ERROR" in resp:
        logger.warning("ClamAV 扫描错误 file=%s resp=%s", filename, resp)

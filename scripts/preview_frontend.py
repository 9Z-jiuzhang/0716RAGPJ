#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地前端预览：模拟 docker/nginx/nginx.conf 的路径映射。"""

from __future__ import annotations

import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent / "frontend"
HOST = "127.0.0.1"
PORT = int(os.environ.get("FRONTEND_PREVIEW_PORT", "5500"))


def resolve(path: str) -> Path | None:
    """按 Nginx 规则把 URL 映射到 frontend 目录下的文件。"""
    raw = unquote(urlparse(path).path)
    if raw.startswith("/assets/"):
        rel = raw[len("/assets/") :]
        candidate = (ROOT / "shared" / rel).resolve()
    elif raw == "/admin" or raw.startswith("/admin/"):
        rel = raw[len("/admin") :].lstrip("/") or "index.html"
        candidate = (ROOT / "admin" / rel).resolve()
        if candidate.is_dir():
            candidate = candidate / "index.html"
    else:
        rel = raw.lstrip("/") or "index.html"
        candidate = (ROOT / "guest" / rel).resolve()
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.exists():
            candidate = (ROOT / "guest" / "index.html").resolve()

    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError:
        return None
    return candidate if candidate.exists() and candidate.is_file() else None


class Handler(BaseHTTPRequestHandler):
    def _send_api_stub(self) -> None:
        """无后端时对 /api/* 返回 501，触发前端演示模式（避免 POST 落静态文件变 405）。"""
        body = b'{"code":501,"message":"API backend not available in frontend preview"}'
        self.send_response(501)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if urlparse(self.path).path.startswith("/api/"):
            self._send_api_stub()
            return
        target = resolve(self.path)
        if target is None:
            self.send_error(404, f"Not Found: {self.path}")
            return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in {
            "application/javascript",
            "application/json",
            "image/svg+xml",
        }:
            ctype = f"{ctype}; charset=utf-8" if "charset" not in ctype else ctype
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path.startswith("/api/"):
            # 读完 body，避免客户端连接异常
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            self._send_api_stub()
            return
        self.send_error(405, "Method Not Allowed")

    def do_PUT(self) -> None:  # noqa: N802
        self.do_POST()

    def do_PATCH(self) -> None:  # noqa: N802
        self.do_POST()

    def do_DELETE(self) -> None:  # noqa: N802
        if urlparse(self.path).path.startswith("/api/"):
            self._send_api_stub()
            return
        self.send_error(405, "Method Not Allowed")

    def log_message(self, fmt: str, *args) -> None:
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))


if __name__ == "__main__":
    os.chdir(ROOT.parent)
    print(f"Frontend preview: http://{HOST}:{PORT}/")
    print(f"Admin:            http://{HOST}:{PORT}/admin/")
    print(f"Root mapped from: {ROOT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

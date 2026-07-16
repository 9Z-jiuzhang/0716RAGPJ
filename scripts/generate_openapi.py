#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 contracts/openapi.json — 仅用于框架阶段契约产出，不进入运行时。"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "contracts" / "openapi.json"

# ---------- helpers ----------

def schema_ref(name: str) -> dict:
    return {"$ref": f"#/components/schemas/{name}"}


def wrap_data(inner: dict | None = None) -> dict:
    """统一响应 BaseResponse，data 可为具体 schema。"""
    props = {
        "code": {"type": "integer", "example": 0, "description": "业务码，0 表示成功"},
        "message": {"type": "string", "example": "success", "description": "提示信息"},
        "request_id": {
            "type": "string",
            "format": "uuid",
            "example": "550e8400-e29b-41d4-a716-446655440000",
            "description": "请求追踪 ID",
        },
    }
    if inner is not None:
        props["data"] = inner
    else:
        props["data"] = {"nullable": True}
    return {
        "type": "object",
        "required": ["code", "message", "request_id"],
        "properties": props,
    }


def resp(description: str, data_schema: dict | None = None, code: int = 200) -> dict:
    return {
        str(code): {
            "description": description,
            "content": {
                "application/json": {
                    "schema": wrap_data(data_schema) if data_schema is not None else wrap_data()
                }
            },
        }
    }


def err_resps(*codes: int) -> dict:
    mapping = {
        400: "请求参数错误",
        401: "未认证或 Token 无效",
        403: "无权限",
        404: "资源不存在",
        409: "资源冲突",
        422: "校验失败",
        500: "服务器内部错误",
        501: "尚未实现（框架占位）",
    }
    out = {}
    for c in codes:
        out[str(c)] = {
            "description": mapping.get(c, "错误"),
            "content": {
                "application/json": {
                    "schema": wrap_data(
                        {
                            "type": "object",
                            "nullable": True,
                            "description": "错误时 data 通常为 null 或错误详情",
                        }
                    )
                }
            },
        }
    return out


def bearer() -> list:
    return [{"BearerAuth": []}]


def op(
    summary: str,
    description: str,
    tags: list[str],
    security: list | None = None,
    parameters: list | None = None,
    request_body: dict | None = None,
    responses: dict | None = None,
    public: bool = False,
) -> dict:
    o: dict = {
        "summary": summary,
        "description": description,
        "tags": tags,
        "responses": responses or {},
    }
    if not public:
        o["security"] = security if security is not None else bearer()
    else:
        o["security"] = []
    if parameters:
        o["parameters"] = parameters
    if request_body:
        o["requestBody"] = request_body
    return o


def json_body(schema_name: str, required: bool = True) -> dict:
    return {
        "required": required,
        "content": {"application/json": {"schema": schema_ref(schema_name)}},
    }


def path_id(name: str = "id", desc: str = "资源 UUID") -> dict:
    return {
        "name": name,
        "in": "path",
        "required": True,
        "description": desc,
        "schema": {"type": "string", "format": "uuid"},
    }


def page_params() -> list:
    return [
        {
            "name": "page",
            "in": "query",
            "description": "页码，从 1 开始",
            "schema": {"type": "integer", "minimum": 1, "default": 1},
        },
        {
            "name": "page_size",
            "in": "query",
            "description": "每页条数，最大 100",
            "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
        },
    ]


# ---------- schemas ----------

schemas: dict = {
    "BaseResponse": wrap_data({"description": "业务数据载荷", "nullable": True}),
    "PaginationMeta": {
        "type": "object",
        "required": ["items", "total", "page", "page_size"],
        "properties": {
            "items": {"type": "array", "items": {}, "description": "当前页数据列表"},
            "total": {"type": "integer", "description": "总条数", "example": 100},
            "page": {"type": "integer", "description": "当前页", "example": 1},
            "page_size": {"type": "integer", "description": "每页大小", "example": 20},
        },
    },
    "RegisterRequest": {
        "type": "object",
        "required": ["username", "password", "email"],
        "properties": {
            "username": {
                "type": "string",
                "minLength": 3,
                "maxLength": 50,
                "description": "用户名，唯一",
                "example": "zhangsan",
            },
            "password": {
                "type": "string",
                "minLength": 8,
                "maxLength": 128,
                "description": "密码，明文传输（须 HTTPS）",
                "example": "Passw0rd!",
            },
            "email": {
                "type": "string",
                "format": "email",
                "description": "邮箱，唯一",
                "example": "zhangsan@example.com",
            },
            "nickname": {
                "type": "string",
                "minLength": 1,
                "maxLength": 100,
                "description": "昵称，可选",
                "example": "张三",
            },
        },
    },
    "LoginRequest": {
        "type": "object",
        "required": ["username", "password"],
        "properties": {
            "username": {"type": "string", "example": "zhangsan"},
            "password": {"type": "string", "example": "Passw0rd!"},
        },
    },
    "TokenResponse": {
        "type": "object",
        "required": ["access_token", "refresh_token", "token_type", "expires_in"],
        "properties": {
            "access_token": {"type": "string", "description": "访问令牌 JWT"},
            "refresh_token": {"type": "string", "description": "刷新令牌 JWT"},
            "token_type": {"type": "string", "example": "bearer"},
            "expires_in": {
                "type": "integer",
                "description": "access_token 有效秒数",
                "example": 1800,
            },
        },
    },
    "RefreshRequest": {
        "type": "object",
        "required": ["refresh_token"],
        "properties": {"refresh_token": {"type": "string"}},
    },
    "UserInfoResponse": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "username": {"type": "string"},
            "email": {"type": "string", "format": "email"},
            "nickname": {"type": "string", "nullable": True},
            "status": {
                "type": "string",
                "enum": ["active", "disabled", "pending"],
                "description": "用户状态",
            },
            "roles": {
                "type": "array",
                "items": {"type": "string"},
                "description": "角色名称列表",
            },
            "permissions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "权限标识列表，如 kb:read",
            },
            "created_at": {"type": "string", "format": "date-time"},
        },
    },
    "ChangePasswordRequest": {
        "type": "object",
        "required": ["old_password", "new_password"],
        "properties": {
            "old_password": {"type": "string"},
            "new_password": {"type": "string", "minLength": 8, "maxLength": 128},
        },
    },
    "UserListItem": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "username": {"type": "string"},
            "email": {"type": "string"},
            "nickname": {"type": "string", "nullable": True},
            "status": {"type": "string"},
            "role_names": {"type": "array", "items": {"type": "string"}},
            "created_at": {"type": "string", "format": "date-time"},
            "last_login_at": {"type": "string", "format": "date-time", "nullable": True},
        },
    },
    "UserListResponse": {
        "allOf": [
            schema_ref("PaginationMeta"),
            {
                "type": "object",
                "properties": {
                    "items": {"type": "array", "items": schema_ref("UserListItem")}
                },
            },
        ]
    },
    "UpdateUserRequest": {
        "type": "object",
        "properties": {
            "nickname": {"type": "string", "nullable": True},
            "email": {"type": "string", "format": "email", "nullable": True},
        },
    },
    "UpdateUserStatusRequest": {
        "type": "object",
        "required": ["status"],
        "properties": {
            "status": {"type": "string", "enum": ["active", "disabled"]},
        },
    },
    "UpdateUserRolesRequest": {
        "type": "object",
        "required": ["role_ids"],
        "properties": {
            "role_ids": {
                "type": "array",
                "items": {"type": "string", "format": "uuid"},
                "description": "角色 UUID 列表，全量覆盖",
            }
        },
    },
    "ResetPasswordRequest": {
        "type": "object",
        "required": ["new_password"],
        "properties": {
            "new_password": {"type": "string", "minLength": 8, "maxLength": 128}
        },
    },
    "RoleListItem": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "name": {"type": "string"},
            "description": {"type": "string", "nullable": True},
            "is_builtin": {"type": "boolean"},
            "permission_count": {"type": "integer"},
        },
    },
    "RoleResponse": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "name": {"type": "string"},
            "description": {"type": "string", "nullable": True},
            "is_builtin": {"type": "boolean"},
            "permission_codes": {"type": "array", "items": {"type": "string"}},
            "kb_ids": {
                "type": "array",
                "items": {"type": "string", "format": "uuid"},
                "description": "角色已授权知识库 ID 列表",
            },
            "created_at": {"type": "string", "format": "date-time"},
        },
    },
    "CreateRoleRequest": {
        "type": "object",
        "required": ["name", "permission_codes"],
        "properties": {
            "name": {"type": "string", "maxLength": 100},
            "description": {"type": "string", "nullable": True},
            "permission_codes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "权限标识列表",
                "example": ["kb:read", "qa:ask"],
            },
        },
    },
    "UpdateRoleRequest": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "nullable": True},
            "description": {"type": "string", "nullable": True},
        },
    },
    "UpdateRolePermissionsRequest": {
        "type": "object",
        "required": ["permission_codes"],
        "properties": {
            "permission_codes": {"type": "array", "items": {"type": "string"}}
        },
    },
    "RoleListResponse": {
        "allOf": [
            schema_ref("PaginationMeta"),
            {
                "type": "object",
                "properties": {
                    "items": {"type": "array", "items": schema_ref("RoleListItem")}
                },
            },
        ]
    },
    "CreateKBRequest": {
        "type": "object",
        "required": ["name", "type", "embedding_model"],
        "properties": {
            "name": {"type": "string", "maxLength": 200, "example": "技术文档库"},
            "type": {
                "type": "string",
                "enum": ["technical_doc", "product_manual", "faq", "general"],
                "description": "知识库类型",
            },
            "tags": {"type": "array", "items": {"type": "string"}, "default": []},
            "description": {"type": "string", "nullable": True},
            "visibility": {
                "type": "string",
                "enum": ["public", "restricted"],
                "default": "restricted",
                "description": "public=访客可检索；restricted=需授权",
            },
            "embedding_model": {"type": "string", "example": "text-embedding-3-small"},
            "chunk_size": {
                "type": "integer",
                "minimum": 100,
                "maximum": 5000,
                "default": 500,
            },
            "chunk_overlap": {
                "type": "integer",
                "minimum": 0,
                "maximum": 1000,
                "default": 50,
            },
        },
    },
    "UpdateKBRequest": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "nullable": True},
            "type": {"type": "string", "nullable": True},
            "tags": {"type": "array", "items": {"type": "string"}, "nullable": True},
            "description": {"type": "string", "nullable": True},
            "visibility": {"type": "string", "nullable": True},
            "embedding_model": {"type": "string", "nullable": True},
            "chunk_size": {"type": "integer", "nullable": True},
            "chunk_overlap": {"type": "integer", "nullable": True},
        },
    },
    "KnowledgeBaseListItem": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "name": {"type": "string"},
            "type": {"type": "string"},
            "visibility": {"type": "string"},
            "status": {"type": "string"},
            "doc_count": {"type": "integer"},
            "updated_at": {"type": "string", "format": "date-time"},
        },
    },
    "KnowledgeBaseResponse": {
        "type": "object",
        "description": "知识库完整信息（含统计）",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "name": {"type": "string"},
            "type": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "description": {"type": "string", "nullable": True},
            "visibility": {"type": "string"},
            "embedding_model": {"type": "string"},
            "chunk_size": {"type": "integer"},
            "chunk_overlap": {"type": "integer"},
            "status": {
                "type": "string",
                "enum": ["active", "vectorizing", "archived", "deleted"],
            },
            "current_index_version": {"type": "string", "nullable": True},
            "doc_count": {"type": "integer"},
            "chunk_count": {"type": "integer"},
            "creator_id": {"type": "string", "format": "uuid"},
            "created_at": {"type": "string", "format": "date-time"},
            "updated_at": {"type": "string", "format": "date-time"},
        },
    },
    "KBListResponse": {
        "allOf": [
            schema_ref("PaginationMeta"),
            {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": schema_ref("KnowledgeBaseListItem"),
                    }
                },
            },
        ]
    },
    "VectorizeStatusResponse": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "任务状态"},
            "progress_percent": {"type": "number", "example": 45.5},
            "current_doc": {"type": "integer"},
            "total_docs": {"type": "integer"},
            "started_at": {"type": "string", "format": "date-time", "nullable": True},
            "error_message": {"type": "string", "nullable": True},
        },
    },
    "KBPermissionGrant": {
        "type": "object",
        "required": ["permission_code"],
        "properties": {
            "user_id": {"type": "string", "format": "uuid", "nullable": True},
            "role_id": {"type": "string", "format": "uuid", "nullable": True},
            "permission_code": {
                "type": "string",
                "example": "kb:upload",
                "description": "user_id 与 role_id 至少填一个",
            },
        },
    },
    "UpdateKBPermissionsRequest": {
        "type": "object",
        "required": ["grants"],
        "properties": {
            "grants": {
                "type": "array",
                "items": schema_ref("KBPermissionGrant"),
                "description": "权限授予列表（建议全量覆盖语义，实现时在文档中确认）",
            }
        },
    },
    "DocumentListItem": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "filename": {"type": "string"},
            "file_type": {"type": "string"},
            "file_size": {"type": "integer"},
            "chunk_count": {"type": "integer"},
            "status": {"type": "string"},
            "created_at": {"type": "string", "format": "date-time"},
        },
    },
    "DocumentResponse": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "kb_id": {"type": "string", "format": "uuid"},
            "filename": {"type": "string"},
            "file_type": {"type": "string"},
            "file_size": {"type": "integer"},
            "file_path": {"type": "string", "description": "MinIO 对象路径"},
            "chunk_count": {"type": "integer"},
            "status": {
                "type": "string",
                "description": "uploaded/parsing/processing/pending_segment/vectorizing/ready/error/archived",
            },
            "error_message": {"type": "string", "nullable": True},
            "creator_id": {"type": "string", "format": "uuid"},
            "created_at": {"type": "string", "format": "date-time"},
            "updated_at": {"type": "string", "format": "date-time"},
        },
    },
    "DocumentListResponse": {
        "allOf": [
            schema_ref("PaginationMeta"),
            {
                "type": "object",
                "properties": {
                    "items": {"type": "array", "items": schema_ref("DocumentListItem")}
                },
            },
        ]
    },
    "UpdateSegmentRulesRequest": {
        "type": "object",
        "required": ["chunk_size", "chunk_overlap"],
        "properties": {
            "chunk_size": {"type": "integer", "minimum": 100, "maximum": 5000},
            "chunk_overlap": {"type": "integer", "minimum": 0, "maximum": 1000},
            "separators": {
                "type": "array",
                "items": {"type": "string"},
                "nullable": True,
            },
            "split_mode": {"type": "string", "nullable": True},
        },
    },
    "DocumentChunkResponse": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "document_id": {"type": "string", "format": "uuid"},
            "chunk_index": {"type": "integer"},
            "content": {"type": "string"},
            "char_count": {"type": "integer"},
            "metadata": {"type": "object"},
            "is_enabled": {"type": "boolean"},
        },
    },
    "UpdateChunkRequest": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "nullable": True},
            "is_enabled": {"type": "boolean", "nullable": True},
            "metadata": {"type": "object", "nullable": True},
        },
    },
    "ChunkListResponse": {
        "allOf": [
            schema_ref("PaginationMeta"),
            {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": schema_ref("DocumentChunkResponse"),
                    }
                },
            },
        ]
    },
    "NormalizeResponse": {
        "type": "object",
        "properties": {
            "normalized_content": {"type": "string"},
            "stats": {
                "type": "object",
                "properties": {
                    "removed_blank_lines": {"type": "integer"},
                    "encoding_fixes": {"type": "integer"},
                },
            },
        },
    },
    "AskRequest": {
        "type": "object",
        "required": ["question"],
        "properties": {
            "question": {
                "type": "string",
                "minLength": 1,
                "maxLength": 2000,
                "example": "如何配置知识库权限？",
            },
            "session_id": {
                "type": "string",
                "format": "uuid",
                "nullable": True,
                "description": "不传则创建新会话",
            },
            "kb_ids": {
                "type": "array",
                "items": {"type": "string", "format": "uuid"},
                "nullable": True,
                "description": "限定检索知识库；默认全部可访问范围",
            },
            "strategy": {
                "type": "string",
                "enum": ["vector", "fulltext", "hybrid"],
                "default": "hybrid",
            },
            "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            "temperature": {
                "type": "number",
                "minimum": 0,
                "maximum": 2,
                "default": 0.7,
            },
        },
    },
    "CitationResponse": {
        "type": "object",
        "properties": {
            "doc_id": {"type": "string", "format": "uuid"},
            "doc_name": {"type": "string"},
            "chunk_index": {"type": "integer"},
            "content": {"type": "string"},
            "score": {"type": "number"},
        },
    },
    "AskEventResponse": {
        "type": "object",
        "description": "SSE 事件 data 字段结构",
        "properties": {
            "event": {
                "type": "string",
                "enum": ["chunk", "citations", "done", "error"],
            },
            "content": {"type": "string", "nullable": True},
            "citations": {
                "type": "array",
                "items": schema_ref("CitationResponse"),
                "nullable": True,
            },
            "session_id": {"type": "string", "format": "uuid"},
            "message_id": {"type": "string", "format": "uuid"},
            "request_id": {"type": "string"},
        },
    },
    "SessionResponse": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "title": {"type": "string"},
            "kb_names": {"type": "array", "items": {"type": "string"}},
            "message_count": {"type": "integer"},
            "created_at": {"type": "string", "format": "date-time"},
            "updated_at": {"type": "string", "format": "date-time"},
        },
    },
    "SessionListResponse": {
        "allOf": [
            schema_ref("PaginationMeta"),
            {
                "type": "object",
                "properties": {
                    "items": {"type": "array", "items": schema_ref("SessionResponse")}
                },
            },
        ]
    },
    "MessageResponse": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "role": {"type": "string", "enum": ["user", "assistant", "system"]},
            "content": {"type": "string"},
            "citations": {
                "type": "array",
                "items": schema_ref("CitationResponse"),
                "nullable": True,
            },
            "token_count": {"type": "integer"},
            "created_at": {"type": "string", "format": "date-time"},
        },
    },
    "MessageListResponse": {
        "allOf": [
            schema_ref("PaginationMeta"),
            {
                "type": "object",
                "properties": {
                    "items": {"type": "array", "items": schema_ref("MessageResponse")}
                },
            },
        ]
    },
    "RenameSessionRequest": {
        "type": "object",
        "required": ["title"],
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 100}
        },
    },
    "FeedbackRequest": {
        "type": "object",
        "required": ["message_id", "rating"],
        "properties": {
            "message_id": {"type": "string", "format": "uuid"},
            "rating": {"type": "string", "enum": ["useful", "useless"]},
            "comment": {"type": "string", "nullable": True},
        },
    },
    "TestQuestion": {
        "type": "object",
        "required": ["question"],
        "properties": {
            "question": {"type": "string"},
            "expected_doc_ids": {
                "type": "array",
                "items": {"type": "string", "format": "uuid"},
                "nullable": True,
            },
            "expected_chunk_ids": {
                "type": "array",
                "items": {"type": "string", "format": "uuid"},
                "nullable": True,
            },
        },
    },
    "CreateTestCaseRequest": {
        "type": "object",
        "required": ["name", "questions"],
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string", "nullable": True},
            "questions": {"type": "array", "items": schema_ref("TestQuestion")},
        },
    },
    "UpdateTestCaseRequest": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "nullable": True},
            "description": {"type": "string", "nullable": True},
            "questions": {
                "type": "array",
                "items": schema_ref("TestQuestion"),
                "nullable": True,
            },
        },
    },
    "TestCaseResponse": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "name": {"type": "string"},
            "description": {"type": "string", "nullable": True},
            "question_count": {"type": "integer"},
            "questions": {"type": "array", "items": schema_ref("TestQuestion")},
            "created_at": {"type": "string", "format": "date-time"},
        },
    },
    "TestCaseListResponse": {
        "allOf": [
            schema_ref("PaginationMeta"),
            {
                "type": "object",
                "properties": {
                    "items": {"type": "array", "items": schema_ref("TestCaseResponse")}
                },
            },
        ]
    },
    "TestRunRequest": {
        "type": "object",
        "required": ["kb_ids", "strategy"],
        "properties": {
            "case_id": {
                "type": "string",
                "format": "uuid",
                "nullable": True,
                "description": "不传则使用 questions 做单题/临时测试",
            },
            "kb_ids": {
                "type": "array",
                "items": {"type": "string", "format": "uuid"},
                "minItems": 1,
            },
            "doc_ids": {
                "type": "array",
                "items": {"type": "string", "format": "uuid"},
                "nullable": True,
            },
            "strategy": {"type": "string", "enum": ["vector", "fulltext", "hybrid"]},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            "similarity_threshold": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "default": 0.5,
            },
            "questions": {
                "type": "array",
                "items": {"type": "string"},
                "nullable": True,
            },
        },
    },
    "TestRunResponse": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "case_id": {"type": "string", "format": "uuid", "nullable": True},
            "kb_ids": {"type": "array", "items": {"type": "string", "format": "uuid"}},
            "strategy": {"type": "string"},
            "top_k": {"type": "integer"},
            "status": {"type": "string", "enum": ["running", "completed", "failed"]},
            "total_questions": {"type": "integer"},
            "hit_count": {"type": "integer"},
            "recall_at_k": {"type": "number", "nullable": True},
            "mrr": {"type": "number", "nullable": True},
            "avg_elapsed_ms": {"type": "number", "nullable": True},
            "completed_at": {"type": "string", "format": "date-time", "nullable": True},
        },
    },
    "TestRunListResponse": {
        "allOf": [
            schema_ref("PaginationMeta"),
            {
                "type": "object",
                "properties": {
                    "items": {"type": "array", "items": schema_ref("TestRunResponse")}
                },
            },
        ]
    },
    "TestResultResponse": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "question": {"type": "string"},
            "is_hit": {"type": "boolean"},
            "hit_rank": {"type": "integer", "nullable": True},
            "score": {"type": "number", "nullable": True},
            "strategy": {"type": "string"},
            "elapsed_ms": {"type": "integer", "nullable": True},
            "actual_chunks": {"type": "array", "items": {"type": "object"}},
        },
    },
    "CreateSnapshotRequest": {
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string", "nullable": True},
        },
    },
    "SnapshotResponse": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "kb_id": {"type": "string", "format": "uuid"},
            "name": {"type": "string"},
            "description": {"type": "string", "nullable": True},
            "trigger": {"type": "string"},
            "status": {"type": "string"},
            "doc_count": {"type": "integer"},
            "creator_id": {"type": "string", "format": "uuid"},
            "created_at": {"type": "string", "format": "date-time"},
        },
    },
    "SnapshotListResponse": {
        "allOf": [
            schema_ref("PaginationMeta"),
            {
                "type": "object",
                "properties": {
                    "items": {"type": "array", "items": schema_ref("SnapshotResponse")}
                },
            },
        ]
    },
    "SnapshotDetailResponse": {
        "allOf": [
            schema_ref("SnapshotResponse"),
            {
                "type": "object",
                "properties": {
                    "documents": {"type": "array", "items": {"type": "object"}},
                    "config_snapshot": {"type": "object"},
                },
            },
        ]
    },
    "RollbackPreviewResponse": {
        "type": "object",
        "properties": {
            "affected_documents": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "document_id": {"type": "string"},
                        "filename": {"type": "string"},
                        "change": {
                            "type": "string",
                            "enum": ["added", "deleted", "modified"],
                        },
                    },
                },
            },
            "total_changes": {"type": "integer"},
        },
    },
    "RollbackRequest": {
        "type": "object",
        "required": ["confirm"],
        "properties": {
            "confirm": {
                "type": "boolean",
                "description": "必须为 true 才执行回退",
                "example": True,
            }
        },
    },
    "CreateModelConfigRequest": {
        "type": "object",
        "required": ["name", "model_type", "provider", "model_name"],
        "properties": {
            "name": {"type": "string"},
            "model_type": {"type": "string", "enum": ["llm", "embedding", "rerank"]},
            "provider": {"type": "string", "example": "openai"},
            "model_name": {"type": "string", "example": "gpt-4o"},
            "base_url": {"type": "string", "nullable": True},
            "config": {"type": "object", "nullable": True},
            "timeout_seconds": {"type": "integer", "default": 60},
        },
    },
    "UpdateModelConfigRequest": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "nullable": True},
            "provider": {"type": "string", "nullable": True},
            "model_name": {"type": "string", "nullable": True},
            "base_url": {"type": "string", "nullable": True},
            "config": {"type": "object", "nullable": True},
            "timeout_seconds": {"type": "integer", "nullable": True},
        },
    },
    "ModelConfigResponse": {
        "type": "object",
        "description": "不含密钥明文",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "name": {"type": "string"},
            "model_type": {"type": "string"},
            "provider": {"type": "string"},
            "model_name": {"type": "string"},
            "base_url": {"type": "string", "nullable": True},
            "is_default": {"type": "boolean"},
            "is_enabled": {"type": "boolean"},
            "config": {"type": "object"},
            "timeout_seconds": {"type": "integer"},
        },
    },
    "ModelConfigListResponse": {
        "allOf": [
            schema_ref("PaginationMeta"),
            {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": schema_ref("ModelConfigResponse"),
                    }
                },
            },
        ]
    },
    "SetDefaultRequest": {
        "type": "object",
        "required": ["is_default"],
        "properties": {"is_default": {"type": "boolean"}},
    },
    "ModelStatusRequest": {
        "type": "object",
        "required": ["is_enabled"],
        "properties": {"is_enabled": {"type": "boolean"}},
    },
    "AuditLogResponse": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "user_id": {"type": "string", "format": "uuid", "nullable": True},
            "action": {"type": "string", "example": "kb.create"},
            "resource_type": {"type": "string"},
            "resource_id": {"type": "string", "nullable": True},
            "detail": {"type": "object", "nullable": True},
            "ip_address": {"type": "string", "nullable": True},
            "result": {"type": "string", "enum": ["success", "failure"]},
            "error_message": {"type": "string", "nullable": True},
            "created_at": {"type": "string", "format": "date-time"},
        },
    },
    "AuditLogListResponse": {
        "allOf": [
            schema_ref("PaginationMeta"),
            {
                "type": "object",
                "properties": {
                    "items": {"type": "array", "items": schema_ref("AuditLogResponse")}
                },
            },
        ]
    },
    "HealthResponse": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["healthy", "degraded", "unhealthy"],
            },
            "version": {"type": "string", "example": "2.1.0"},
            "uptime_seconds": {"type": "integer"},
            "checks": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string"},
                        "latency_ms": {"type": "number"},
                    },
                },
                "description": "各组件连通性，如 postgres/redis/chroma/minio",
            },
        },
    },
    "SystemStatsResponse": {
        "type": "object",
        "properties": {
            "user_count": {"type": "integer"},
            "kb_count": {"type": "integer"},
            "doc_count": {"type": "integer"},
            "active_sessions": {"type": "integer"},
            "task_queue_size": {"type": "integer"},
        },
    },
}

# ---------- paths ----------

paths: dict = {}

# Auth
paths["/auth/register"] = {
    "post": op(
        "用户注册",
        "公开接口。创建账号后默认角色为 user；密码服务端 bcrypt 哈希存储。",
        ["认证"],
        public=True,
        request_body=json_body("RegisterRequest"),
        responses={
            **resp("注册成功", schema_ref("UserInfoResponse"), 201),
            **err_resps(400, 409, 422, 500),
        },
    )
}
paths["/auth/login"] = {
    "post": op(
        "用户登录",
        "公开接口。校验用户名密码，返回 access/refresh JWT。禁用用户返回 403。",
        ["认证"],
        public=True,
        request_body=json_body("LoginRequest"),
        responses={
            **resp("登录成功", schema_ref("TokenResponse")),
            **err_resps(400, 401, 403, 422, 500),
        },
    )
}
paths["/auth/refresh"] = {
    "post": op(
        "刷新 Token",
        "使用 refresh_token 换取新的 access_token（及可选旋转 refresh_token）。",
        ["认证"],
        request_body=json_body("RefreshRequest"),
        responses={
            **resp("刷新成功", schema_ref("TokenResponse")),
            **err_resps(401, 422, 500),
        },
    )
}
paths["/auth/me"] = {
    "get": op(
        "当前用户信息",
        "返回当前登录用户资料、角色与权限标识，供前端渲染菜单与按钮。",
        ["认证"],
        responses={
            **resp("成功", schema_ref("UserInfoResponse")),
            **err_resps(401, 500),
        },
    )
}

# Users
paths["/users"] = {
    "get": op(
        "用户列表",
        "分页查询用户。支持 keyword 搜索用户名/邮箱。需要 user:read。",
        ["用户管理"],
        parameters=page_params()
        + [
            {
                "name": "keyword",
                "in": "query",
                "schema": {"type": "string"},
                "description": "搜索关键字",
            },
            {
                "name": "status",
                "in": "query",
                "schema": {"type": "string", "enum": ["active", "disabled", "pending"]},
            },
        ],
        responses={
            **resp("成功", schema_ref("UserListResponse")),
            **err_resps(401, 403, 500),
        },
    )
}
paths["/users/{id}"] = {
    "get": op(
        "用户详情",
        "按 ID 获取用户完整信息。需要 user:read。",
        ["用户管理"],
        parameters=[path_id()],
        responses={
            **resp("成功", schema_ref("UserInfoResponse")),
            **err_resps(401, 403, 404, 500),
        },
    ),
    "put": op(
        "修改用户信息",
        "更新昵称、邮箱等基础字段。需要 user:write。",
        ["用户管理"],
        parameters=[path_id()],
        request_body=json_body("UpdateUserRequest"),
        responses={
            **resp("成功", schema_ref("UserInfoResponse")),
            **err_resps(400, 401, 403, 404, 422, 500),
        },
    ),
}
paths["/users/{id}/status"] = {
    "patch": op(
        "启用/禁用用户",
        "禁用后应立即拒绝该用户新请求；历史数据保留。需要 user:write。",
        ["用户管理"],
        parameters=[path_id()],
        request_body=json_body("UpdateUserStatusRequest"),
        responses={
            **resp("成功", schema_ref("UserInfoResponse")),
            **err_resps(401, 403, 404, 422, 500),
        },
    )
}
paths["/users/{id}/roles"] = {
    "put": op(
        "修改用户角色",
        "全量覆盖用户角色绑定。变更需记审计日志。需要 user:write。",
        ["用户管理"],
        parameters=[path_id()],
        request_body=json_body("UpdateUserRolesRequest"),
        responses={
            **resp("成功", schema_ref("UserInfoResponse")),
            **err_resps(401, 403, 404, 422, 500),
        },
    )
}
paths["/users/{id}/reset-password"] = {
    "post": op(
        "重置密码",
        "管理员重置指定用户密码。需要 user:write。",
        ["用户管理"],
        parameters=[path_id()],
        request_body=json_body("ResetPasswordRequest"),
        responses={**resp("成功"), **err_resps(401, 403, 404, 422, 500)},
    )
}

# Roles
paths["/roles"] = {
    "get": op(
        "角色列表",
        "分页列出角色。需要 role:read。",
        ["角色管理"],
        parameters=page_params(),
        responses={
            **resp("成功", schema_ref("RoleListResponse")),
            **err_resps(401, 403, 500),
        },
    ),
    "post": op(
        "创建角色",
        "创建自定义角色并绑定权限标识。需要 role:write。",
        ["角色管理"],
        request_body=json_body("CreateRoleRequest"),
        responses={
            **resp("创建成功", schema_ref("RoleResponse"), 201),
            **err_resps(400, 401, 403, 409, 422, 500),
        },
    ),
}
paths["/roles/{id}"] = {
    "put": op(
        "修改角色",
        "修改名称/描述。内置角色不可删除，名称变更策略由实现约定。需要 role:write。",
        ["角色管理"],
        parameters=[path_id()],
        request_body=json_body("UpdateRoleRequest"),
        responses={
            **resp("成功", schema_ref("RoleResponse")),
            **err_resps(401, 403, 404, 422, 500),
        },
    ),
    "delete": op(
        "删除角色",
        "删除非内置角色；若仍有用户绑定应返回 409。需要 role:write。",
        ["角色管理"],
        parameters=[path_id()],
        responses={**resp("删除成功"), **err_resps(401, 403, 404, 409, 500)},
    ),
}
paths["/roles/{id}/permissions"] = {
    "put": op(
        "配置角色权限",
        "全量覆盖角色的功能权限标识列表。需要 role:write。",
        ["角色管理"],
        parameters=[path_id()],
        request_body=json_body("UpdateRolePermissionsRequest"),
        responses={
            **resp("成功", schema_ref("RoleResponse")),
            **err_resps(401, 403, 404, 422, 500),
        },
    )
}

# Models
paths["/models"] = {
    "get": op(
        "模型配置列表",
        "列出 LLM / Embedding / Rerank 配置（不含密钥明文）。需要 model:read。",
        ["大模型管理"],
        parameters=page_params()
        + [
            {
                "name": "model_type",
                "in": "query",
                "schema": {"type": "string", "enum": ["llm", "embedding", "rerank"]},
            }
        ],
        responses={
            **resp("成功", schema_ref("ModelConfigListResponse")),
            **err_resps(401, 403, 500),
        },
    ),
    "post": op(
        "添加模型配置",
        "新增模型接入配置。密钥建议存环境变量或加密字段。需要 model:write。",
        ["大模型管理"],
        request_body=json_body("CreateModelConfigRequest"),
        responses={
            **resp("创建成功", schema_ref("ModelConfigResponse"), 201),
            **err_resps(400, 401, 403, 422, 500),
        },
    ),
}
paths["/models/{id}"] = {
    "put": op(
        "修改模型配置",
        "更新模型参数。需要 model:write。",
        ["大模型管理"],
        parameters=[path_id()],
        request_body=json_body("UpdateModelConfigRequest"),
        responses={
            **resp("成功", schema_ref("ModelConfigResponse")),
            **err_resps(401, 403, 404, 422, 500),
        },
    )
}
paths["/models/{id}/status"] = {
    "patch": op(
        "启用/禁用模型",
        "禁用后不可被新请求选用。需要 model:write。",
        ["大模型管理"],
        parameters=[path_id()],
        request_body=json_body("ModelStatusRequest"),
        responses={
            **resp("成功", schema_ref("ModelConfigResponse")),
            **err_resps(401, 403, 404, 422, 500),
        },
    )
}
paths["/models/{id}/default"] = {
    "put": op(
        "设置默认模型",
        "将指定模型设为同类型默认；同类型其他默认应取消。需要 model:write。",
        ["大模型管理"],
        parameters=[path_id()],
        request_body=json_body("SetDefaultRequest"),
        responses={
            **resp("成功", schema_ref("ModelConfigResponse")),
            **err_resps(401, 403, 404, 422, 500),
        },
    )
}

# Knowledge bases
paths["/knowledge-bases"] = {
    "get": op(
        "知识库列表",
        "仅返回当前用户有权限访问的知识库。需登录。",
        ["知识库管理"],
        parameters=page_params()
        + [
            {"name": "keyword", "in": "query", "schema": {"type": "string"}},
            {
                "name": "type",
                "in": "query",
                "schema": {
                    "type": "string",
                    "enum": ["technical_doc", "product_manual", "faq", "general"],
                },
            },
        ],
        responses={
            **resp("成功", schema_ref("KBListResponse")),
            **err_resps(401, 500),
        },
    ),
    "post": op(
        "创建知识库",
        "创建知识库元信息与分段默认规则。需要 kb:write。",
        ["知识库管理"],
        request_body=json_body("CreateKBRequest"),
        responses={
            **resp("创建成功", schema_ref("KnowledgeBaseResponse"), 201),
            **err_resps(400, 401, 403, 422, 500),
        },
    ),
}
paths["/knowledge-bases/{id}"] = {
    "get": op(
        "知识库详情",
        "返回元信息与文档/分段统计。需要对该库具备 kb:read。",
        ["知识库管理"],
        parameters=[path_id(desc="知识库 UUID")],
        responses={
            **resp("成功", schema_ref("KnowledgeBaseResponse")),
            **err_resps(401, 403, 404, 500),
        },
    ),
    "put": op(
        "修改知识库",
        "更新元信息；变更权限相关字段前应触发自动快照（P1）。需要 kb:write。",
        ["知识库管理"],
        parameters=[path_id(desc="知识库 UUID")],
        request_body=json_body("UpdateKBRequest"),
        responses={
            **resp("成功", schema_ref("KnowledgeBaseResponse")),
            **err_resps(401, 403, 404, 422, 500),
        },
    ),
    "delete": op(
        "删除知识库",
        "逻辑删除或级联清理策略由实现约定；须记审计。需要 kb:write。",
        ["知识库管理"],
        parameters=[path_id(desc="知识库 UUID")],
        responses={**resp("删除成功"), **err_resps(401, 403, 404, 500)},
    ),
}
paths["/knowledge-bases/{id}/re-vectorize"] = {
    "post": op(
        "重新向量化",
        "异步任务重建向量索引；返回任务受理结果，进度见 vectorize-status。需要 kb:vectorize。",
        ["知识库管理"],
        parameters=[path_id(desc="知识库 UUID")],
        responses={
            **resp("已受理", schema_ref("VectorizeStatusResponse"), 202),
            **err_resps(401, 403, 404, 409, 500),
        },
    )
}
paths["/knowledge-bases/{id}/vectorize-status"] = {
    "get": op(
        "向量化进度",
        "查询当前知识库向量化任务进度。需要 kb:vectorize。",
        ["知识库管理"],
        parameters=[path_id(desc="知识库 UUID")],
        responses={
            **resp("成功", schema_ref("VectorizeStatusResponse")),
            **err_resps(401, 403, 404, 500),
        },
    )
}
paths["/knowledge-bases/{id}/permissions"] = {
    "put": op(
        "配置知识库权限",
        "为用户/角色授予知识库级权限标识。变更前建议自动快照。需要 kb:write。",
        ["知识库管理"],
        parameters=[path_id(desc="知识库 UUID")],
        request_body=json_body("UpdateKBPermissionsRequest"),
        responses={**resp("成功"), **err_resps(401, 403, 404, 422, 500)},
    )
}

# Documents
kb_doc = "/knowledge-bases/{kb_id}/documents"
paths[kb_doc] = {
    "get": op(
        "文档列表",
        "分页列出知识库下文档，支持按文件名搜索。需要 doc:read。",
        ["文档管理"],
        parameters=[path_id("kb_id", "知识库 UUID")]
        + page_params()
        + [{"name": "keyword", "in": "query", "schema": {"type": "string"}}],
        responses={
            **resp("成功", schema_ref("DocumentListResponse")),
            **err_resps(401, 403, 404, 500),
        },
    )
}
paths[f"{kb_doc}/upload"] = {
    "post": op(
        "上传文档",
        "multipart 上传。首期支持 pdf/doc/docx/txt/md；csv/xlsx/pptx 为 P1。"
        "上传后进入解析-分段-向量化流水线。需要 kb:upload。",
        ["文档管理"],
        parameters=[path_id("kb_id", "知识库 UUID")],
        request_body={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {
                            "file": {
                                "type": "string",
                                "format": "binary",
                                "description": "文档文件，单文件建议 < 100MB",
                            }
                        },
                    }
                }
            },
        },
        responses={
            **resp("上传成功", schema_ref("DocumentResponse"), 201),
            **err_resps(400, 401, 403, 404, 413, 422, 500),
        },
    )
}
paths[f"{kb_doc}/{{id}}"] = {
    "get": op(
        "文档详情",
        "返回文档元信息与处理状态。需要 doc:read。",
        ["文档管理"],
        parameters=[path_id("kb_id", "知识库 UUID"), path_id()],
        responses={
            **resp("成功", schema_ref("DocumentResponse")),
            **err_resps(401, 403, 404, 500),
        },
    ),
    "delete": op(
        "删除文档",
        "删除文档及分段/向量；操作前自动快照（P1）。需要 doc:write。",
        ["文档管理"],
        parameters=[path_id("kb_id", "知识库 UUID"), path_id()],
        responses={**resp("删除成功"), **err_resps(401, 403, 404, 500)},
    ),
}
paths[f"{kb_doc}/{{id}}/segment-rules"] = {
    "put": op(
        "修改分段规则",
        "仅更新规则，不立即重分段；配合 re-segment 使用。需要 doc:segment。",
        ["文档管理"],
        parameters=[path_id("kb_id", "知识库 UUID"), path_id()],
        request_body=json_body("UpdateSegmentRulesRequest"),
        responses={
            **resp("成功", schema_ref("DocumentResponse")),
            **err_resps(401, 403, 404, 422, 500),
        },
    )
}
paths[f"{kb_doc}/{{id}}/re-segment"] = {
    "post": op(
        "重新分段",
        "按当前规则重新分段并触发向量化。异步任务。需要 doc:segment。",
        ["文档管理"],
        parameters=[path_id("kb_id", "知识库 UUID"), path_id()],
        responses={
            **resp("已受理", schema_ref("DocumentResponse"), 202),
            **err_resps(401, 403, 404, 409, 500),
        },
    )
}
paths[f"{kb_doc}/{{id}}/normalize"] = {
    "post": op(
        "文档规范化",
        "清洗空白行、编码等问题，返回规范化结果统计。需要 doc:write。",
        ["文档管理"],
        parameters=[path_id("kb_id", "知识库 UUID"), path_id()],
        responses={
            **resp("成功", schema_ref("NormalizeResponse")),
            **err_resps(401, 403, 404, 500),
        },
    )
}
paths[f"{kb_doc}/{{id}}/chunks"] = {
    "get": op(
        "分段预览",
        "分页返回文档分段内容，供人工校对。需要 doc:read。",
        ["文档管理"],
        parameters=[path_id("kb_id", "知识库 UUID"), path_id()] + page_params(),
        responses={
            **resp("成功", schema_ref("ChunkListResponse")),
            **err_resps(401, 403, 404, 500),
        },
    )
}
paths[f"{kb_doc}/{{id}}/chunks/{{chunk_id}}"] = {
    "put": op(
        "编辑分段",
        "编辑分段文本、启用/禁用；禁用分段不参与检索。需要 doc:segment。",
        ["文档管理"],
        parameters=[
            path_id("kb_id", "知识库 UUID"),
            path_id(),
            path_id("chunk_id", "分段 UUID"),
        ],
        request_body=json_body("UpdateChunkRequest"),
        responses={
            **resp("成功", schema_ref("DocumentChunkResponse")),
            **err_resps(401, 403, 404, 422, 500),
        },
    )
}

# QA
paths["/qa/ask"] = {
    "post": op(
        "发送问题（SSE）",
        "流式问答。Content-Type: text/event-stream。"
        "事件类型：chunk / citations / done / error。"
        "访客可访问：仅检索 visibility=public 的知识库；"
        "已登录用户按授权范围过滤。可选认证（Bearer 可选）。",
        ["智能问答"],
        public=True,
        security=[{"BearerAuth": []}, {}],
        request_body=json_body("AskRequest"),
        responses={
            "200": {
                "description": "SSE 事件流",
                "content": {
                    "text/event-stream": {
                        "schema": schema_ref("AskEventResponse"),
                    }
                },
            },
            **err_resps(400, 401, 403, 422, 500),
        },
    )
}
paths["/qa/sessions"] = {
    "get": op(
        "我的会话列表",
        "仅返回当前登录用户的会话。需登录。",
        ["智能问答"],
        parameters=page_params(),
        responses={
            **resp("成功", schema_ref("SessionListResponse")),
            **err_resps(401, 500),
        },
    )
}
paths["/qa/sessions/{id}"] = {
    "get": op(
        "会话消息历史",
        "分页返回会话内消息（含引用）。需登录且只能访问本人会话。",
        ["智能问答"],
        parameters=[path_id()] + page_params(),
        responses={
            **resp("成功", schema_ref("MessageListResponse")),
            **err_resps(401, 403, 404, 500),
        },
    ),
    "put": op(
        "重命名会话",
        "修改会话标题。需登录。",
        ["智能问答"],
        parameters=[path_id()],
        request_body=json_body("RenameSessionRequest"),
        responses={
            **resp("成功", schema_ref("SessionResponse")),
            **err_resps(401, 403, 404, 422, 500),
        },
    ),
    "delete": op(
        "删除会话",
        "删除会话及其消息。需登录。",
        ["智能问答"],
        parameters=[path_id()],
        responses={**resp("删除成功"), **err_resps(401, 403, 404, 500)},
    ),
}
paths["/qa/feedback"] = {
    "post": op(
        "回答反馈",
        "对助手消息标记有用/无用，可选评论。需登录。",
        ["智能问答"],
        request_body=json_body("FeedbackRequest"),
        responses={**resp("成功"), **err_resps(401, 404, 422, 500)},
    )
}

# Hit tests
paths["/hit-tests/cases"] = {
    "get": op(
        "测试用例列表",
        "列出命中率测试用例集。需要 test:read。",
        ["命中率测试"],
        parameters=page_params(),
        responses={
            **resp("成功", schema_ref("TestCaseListResponse")),
            **err_resps(401, 403, 500),
        },
    ),
    "post": op(
        "创建测试用例",
        "创建含期望文档/分段的问题集。需要 test:write。",
        ["命中率测试"],
        request_body=json_body("CreateTestCaseRequest"),
        responses={
            **resp("创建成功", schema_ref("TestCaseResponse"), 201),
            **err_resps(401, 403, 422, 500),
        },
    ),
}
paths["/hit-tests/cases/{id}"] = {
    "put": op(
        "编辑测试用例",
        "更新用例名称、描述或问题列表。需要 test:write。",
        ["命中率测试"],
        parameters=[path_id()],
        request_body=json_body("UpdateTestCaseRequest"),
        responses={
            **resp("成功", schema_ref("TestCaseResponse")),
            **err_resps(401, 403, 404, 422, 500),
        },
    ),
    "delete": op(
        "删除测试用例",
        "删除用例集（历史运行记录是否级联由实现约定）。需要 test:write。",
        ["命中率测试"],
        parameters=[path_id()],
        responses={**resp("删除成功"), **err_resps(401, 403, 404, 500)},
    ),
}
paths["/hit-tests/runs"] = {
    "post": op(
        "执行命中率测试",
        "可基于用例集或临时 questions；异步执行，返回 run 记录。需要 test:write。"
        "只能测试当前有权限的知识库范围。",
        ["命中率测试"],
        request_body=json_body("TestRunRequest"),
        responses={
            **resp("已创建运行", schema_ref("TestRunResponse"), 202),
            **err_resps(401, 403, 422, 500),
        },
    ),
    "get": op(
        "测试运行记录列表",
        "分页查询历史运行。需要 test:read。",
        ["命中率测试"],
        parameters=page_params(),
        responses={
            **resp("成功", schema_ref("TestRunListResponse")),
            **err_resps(401, 403, 500),
        },
    ),
}
paths["/hit-tests/runs/{id}"] = {
    "get": op(
        "测试结果详情",
        "返回运行汇总及各题命中明细。需要 test:read。",
        ["命中率测试"],
        parameters=[path_id()],
        responses={
            **resp(
                "成功",
                {
                    "type": "object",
                    "properties": {
                        "run": schema_ref("TestRunResponse"),
                        "results": {
                            "type": "array",
                            "items": schema_ref("TestResultResponse"),
                        },
                    },
                },
            ),
            **err_resps(401, 403, 404, 500),
        },
    )
}
paths["/hit-tests/runs/{id}/export"] = {
    "get": op(
        "导出测试结果 CSV",
        "下载 CSV 文件。需要 test:read。",
        ["命中率测试"],
        parameters=[path_id()],
        responses={
            "200": {
                "description": "CSV 文件",
                "content": {
                    "text/csv": {
                        "schema": {"type": "string", "format": "binary"}
                    }
                },
            },
            **err_resps(401, 403, 404, 500),
        },
    )
}

# Snapshots
snap = "/knowledge-bases/{kb_id}/snapshots"
paths[snap] = {
    "get": op(
        "快照列表",
        "列出知识库快照。需要 snapshot:read。",
        ["快照管理"],
        parameters=[path_id("kb_id", "知识库 UUID")] + page_params(),
        responses={
            **resp("成功", schema_ref("SnapshotListResponse")),
            **err_resps(401, 403, 404, 500),
        },
    ),
    "post": op(
        "手动创建快照",
        "创建可恢复快照（文档/分段规则/权限配置引用等）。需要 snapshot:write。",
        ["快照管理"],
        parameters=[path_id("kb_id", "知识库 UUID")],
        request_body=json_body("CreateSnapshotRequest"),
        responses={
            **resp("创建成功", schema_ref("SnapshotResponse"), 201),
            **err_resps(401, 403, 404, 422, 500),
        },
    ),
}
paths[f"{snap}/{{id}}"] = {
    "get": op(
        "快照详情",
        "含文档列表与配置快照。需要 snapshot:read。",
        ["快照管理"],
        parameters=[path_id("kb_id", "知识库 UUID"), path_id()],
        responses={
            **resp("成功", schema_ref("SnapshotDetailResponse")),
            **err_resps(401, 403, 404, 500),
        },
    ),
    "delete": op(
        "删除快照",
        "删除指定快照。需要 snapshot:write。",
        ["快照管理"],
        parameters=[path_id("kb_id", "知识库 UUID"), path_id()],
        responses={**resp("删除成功"), **err_resps(401, 403, 404, 500)},
    ),
}
paths[f"{snap}/{{id}}/preview"] = {
    "post": op(
        "回退差异预览",
        "对比当前状态与快照，列出将新增/删除/修改的文档。需要 snapshot:read。",
        ["快照管理"],
        parameters=[path_id("kb_id", "知识库 UUID"), path_id()],
        responses={
            **resp("成功", schema_ref("RollbackPreviewResponse")),
            **err_resps(401, 403, 404, 500),
        },
    )
}
paths[f"{snap}/{{id}}/rollback"] = {
    "post": op(
        "回退到快照",
        "confirm 必须为 true。回退后需重建向量索引。需要 snapshot:restore。"
        "回退前应创建 rollback_protection 快照。",
        ["快照管理"],
        parameters=[path_id("kb_id", "知识库 UUID"), path_id()],
        request_body=json_body("RollbackRequest"),
        responses={
            **resp("回退已受理", code=202),
            **err_resps(400, 401, 403, 404, 422, 500),
        },
    )
}

# Audit
paths["/audit/logs"] = {
    "get": op(
        "审计日志列表",
        "分页+多条件筛选。需要 audit:read。",
        ["审计日志"],
        parameters=page_params()
        + [
            {"name": "user_id", "in": "query", "schema": {"type": "string", "format": "uuid"}},
            {"name": "action", "in": "query", "schema": {"type": "string"}},
            {"name": "resource_type", "in": "query", "schema": {"type": "string"}},
            {"name": "resource_id", "in": "query", "schema": {"type": "string"}},
            {
                "name": "result",
                "in": "query",
                "schema": {"type": "string", "enum": ["success", "failure"]},
            },
            {"name": "start_date", "in": "query", "schema": {"type": "string", "format": "date-time"}},
            {"name": "end_date", "in": "query", "schema": {"type": "string", "format": "date-time"}},
        ],
        responses={
            **resp("成功", schema_ref("AuditLogListResponse")),
            **err_resps(401, 403, 500),
        },
    )
}
paths["/audit/logs/{id}"] = {
    "get": op(
        "审计日志详情",
        "含操作 detail JSON（变更前后对比）。需要 audit:read。",
        ["审计日志"],
        parameters=[path_id()],
        responses={
            **resp("成功", schema_ref("AuditLogResponse")),
            **err_resps(401, 403, 404, 500),
        },
    )
}

# Monitor
paths["/monitor/health"] = {
    "get": op(
        "系统健康检查",
        "公开接口。检查 postgres/redis/chroma/minio 等组件连通性。",
        ["系统监控"],
        public=True,
        responses={
            **resp("成功", schema_ref("HealthResponse")),
            **err_resps(500),
        },
    )
}
paths["/monitor/stats"] = {
    "get": op(
        "系统统计概览",
        "用户/知识库/文档/会话/队列规模。需要 system:read。",
        ["系统监控"],
        responses={
            **resp("成功", schema_ref("SystemStatsResponse")),
            **err_resps(401, 403, 500),
        },
    )
}

# Fix 413 in err_resps for upload
err_resps_upload = err_resps(400, 401, 403, 404, 422, 500)
err_resps_upload["413"] = {
    "description": "文件过大",
    "content": {"application/json": {"schema": wrap_data()}},
}
paths[f"{kb_doc}/upload"]["post"]["responses"] = {
    **resp("上传成功", schema_ref("DocumentResponse"), 201),
    **err_resps_upload,
}

doc = {
    "openapi": "3.0.3",
    "info": {
        "title": "AI 知识库 RAG 平台 API",
        "version": "2.1.0",
        "description": (
            "基于大语言模型的智能知识库平台接口契约。\n\n"
            "## 访问端说明\n"
            "- **访客端**：问答（公开知识库）、登录注册；`/qa/ask` 支持可选认证。\n"
            "- **管理端**：用户/角色/知识库/文档/模型/命中率测试/快照/审计/监控。\n\n"
            "## 约定\n"
            "- Base path 已含在 server URL 的 `/api/v1` 中。\n"
            "- 除特别说明外，成功响应均为统一包装：`{code,message,data,request_id}`。\n"
            "- 权限标识格式：`资源:动作`，知识库级权限需叠加授权范围校验。\n"
            "- 契约版本与产品手册 V2.1 同步；变更须团队评审。"
        ),
        "license": {"name": "MIT"},
    },
    "servers": [
        {
            "url": "http://localhost:8080/api/v1",
            "description": "本地 / Docker 统一入口",
        }
    ],
    "tags": [
        {"name": "认证", "description": "注册登录与当前用户"},
        {"name": "用户管理", "description": "管理端用户 CRUD 与角色绑定"},
        {"name": "角色管理", "description": "角色与功能权限"},
        {"name": "大模型管理", "description": "LLM/Embedding/Rerank 配置"},
        {"name": "知识库管理", "description": "知识库元信息、向量化与授权"},
        {"name": "文档管理", "description": "上传、分段、规范化"},
        {"name": "智能问答", "description": "SSE 问答与会话"},
        {"name": "命中率测试", "description": "检索质量评测"},
        {"name": "快照管理", "description": "快照与回退"},
        {"name": "审计日志", "description": "操作审计"},
        {"name": "系统监控", "description": "健康检查与统计"},
    ],
    "paths": paths,
    "components": {
        "securitySchemes": {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "Authorization: Bearer <access_token>",
            }
        },
        "schemas": schemas,
    },
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Wrote {OUT} ({OUT.stat().st_size} bytes), paths={len(paths)}")

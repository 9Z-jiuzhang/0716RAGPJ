#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 docs/openapi.json —— 前后端共用的 OpenAPI 3.0.3 契约。

本脚本是契约的**唯一生成入口**：接口/字段变更时请同步修改此处并重跑
    python scripts/generate_openapi.py

契约与中文说明统一放在 docs/ 目录：
    docs/openapi.json            — 机器可读契约
    docs/API.md                  — 中文接口文档
    docs/API_INTEGRATION_GUIDE.md — 第三方接入指南
    docs/CLOUD_DEPLOY.md         — 云端部署指南
    docs/CONTRACT.md             — 契约使用与变更说明
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "openapi.json"

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def ref(name: str) -> dict:
    return {"$ref": f"#/components/schemas/{name}"}


def wrap_data(inner: dict | None = None) -> dict:
    """统一响应包装 BaseResponse / APIResponse，data 可为具体 schema。"""
    return {
        "type": "object",
        "required": ["code", "message"],
        "properties": {
            "code": {"type": "integer", "example": 0, "description": "业务码，0 表示成功"},
            "message": {"type": "string", "example": "success", "description": "提示信息"},
            "data": inner if inner is not None else {"nullable": True},
            "request_id": {
                "type": "string",
                "format": "uuid",
                "example": "550e8400-e29b-41d4-a716-446655440000",
                "description": "请求追踪 ID",
            },
        },
    }


def page_of(item_ref: dict) -> dict:
    """分页 data 载荷：{items, total, page, page_size}。"""
    return {
        "type": "object",
        "required": ["items", "total", "page", "page_size"],
        "properties": {
            "items": {"type": "array", "items": item_ref, "description": "当前页数据"},
            "total": {"type": "integer", "example": 100, "description": "总条数"},
            "page": {"type": "integer", "example": 1, "description": "当前页（从 1 开始）"},
            "page_size": {"type": "integer", "example": 20, "description": "每页条数"},
        },
    }


def resp(description: str, data_schema: dict | None = None, code: int = 200) -> dict:
    return {
        str(code): {
            "description": description,
            "content": {"application/json": {"schema": wrap_data(data_schema)}},
        }
    }


_ERR_MAP = {
    400: "请求参数错误",
    401: "未认证或 Token 无效/过期",
    403: "无权限或用户被禁用",
    404: "资源不存在或不可见",
    409: "资源冲突（唯一性/内置保护/仍被引用）",
    413: "上传文件过大",
    422: "字段校验失败",
    500: "服务器内部错误",
    502: "上游依赖失败",
}


def err_resps(*codes: int) -> dict:
    out: dict = {}
    for c in codes:
        out[str(c)] = {
            "description": _ERR_MAP.get(c, "错误"),
            "content": {"application/json": {"schema": wrap_data({"nullable": True})}},
        }
    return out


def bearer() -> list:
    return [{"BearerAuth": []}]


def op(
    summary: str,
    description: str,
    tags: list[str],
    *,
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
    o["security"] = [] if public else (security if security is not None else bearer())
    if parameters:
        o["parameters"] = parameters
    if request_body:
        o["requestBody"] = request_body
    return o


def json_body(schema_name: str, required: bool = True) -> dict:
    return {"required": required, "content": {"application/json": {"schema": ref(schema_name)}}}


def path_param(name: str = "id", desc: str = "资源 UUID") -> dict:
    return {
        "name": name,
        "in": "path",
        "required": True,
        "description": desc,
        "schema": {"type": "string", "format": "uuid"},
    }


def q(name: str, desc: str, schema: dict) -> dict:
    return {"name": name, "in": "query", "description": desc, "schema": schema}


def page_params(default_size: int = 20) -> list:
    return [
        q("page", "页码，从 1 开始", {"type": "integer", "minimum": 1, "default": 1}),
        q(
            "page_size",
            "每页条数，最大 100",
            {"type": "integer", "minimum": 1, "maximum": 100, "default": default_size},
        ),
    ]


def prop(t: str, desc: str = "", **kw) -> dict:
    d: dict = {"type": t}
    if desc:
        d["description"] = desc
    d.update(kw)
    return d


def uuid_prop(desc: str = "", nullable: bool = False) -> dict:
    d = {"type": "string", "format": "uuid"}
    if desc:
        d["description"] = desc
    if nullable:
        d["nullable"] = True
    return d


def dt_prop(nullable: bool = False) -> dict:
    d = {"type": "string", "format": "date-time"}
    if nullable:
        d["nullable"] = True
    return d


# ---------------------------------------------------------------------------
# schemas
# ---------------------------------------------------------------------------

schemas: dict = {}

# ---- 通用 ----
schemas["BaseResponse"] = wrap_data({"nullable": True, "description": "业务数据载荷"})

# ---- 认证 ----
schemas["RegisterRequest"] = {
    "type": "object",
    "required": ["username", "password", "email"],
    "properties": {
        "username": prop("string", "用户名，唯一", minLength=3, maxLength=50, example="zhangsan"),
        "password": prop("string", "密码（明文传输，须 HTTPS）", minLength=8, maxLength=128, example="Passw0rd!"),
        "email": prop("string", "邮箱，唯一", format="email", example="zhangsan@example.com"),
        "nickname": prop("string", "昵称", maxLength=100, nullable=True, example="张三"),
    },
}
schemas["LoginRequest"] = {
    "type": "object",
    "required": ["username", "password"],
    "properties": {
        "username": prop("string", example="admin"),
        "password": prop("string", example="Admin123!"),
    },
}
schemas["RefreshRequest"] = {
    "type": "object",
    "required": ["refresh_token"],
    "properties": {"refresh_token": prop("string", "刷新令牌 JWT")},
}
schemas["TokenResponse"] = {
    "type": "object",
    "required": ["access_token", "refresh_token", "token_type", "expires_in"],
    "properties": {
        "access_token": prop("string", "访问令牌 JWT"),
        "refresh_token": prop("string", "刷新令牌 JWT"),
        "token_type": prop("string", example="bearer"),
        "expires_in": prop("integer", "access_token 有效秒数", example=1800),
    },
}
schemas["UserUpdateRequest"] = {
    "type": "object",
    "properties": {
        "nickname": prop("string", "昵称", maxLength=100, nullable=True),
        "email": prop("string", format="email", nullable=True),
        "department": prop("string", "所属部门编码，如 A / B", maxLength=50, nullable=True),
    },
}
schemas["ChangePasswordRequest"] = {
    "type": "object",
    "required": ["old_password", "new_password", "confirm_password"],
    "properties": {
        "old_password": prop("string", "原密码", minLength=1, maxLength=128),
        "new_password": prop("string", "新密码", minLength=8, maxLength=128),
        "confirm_password": prop("string", "确认新密码", minLength=8, maxLength=128),
    },
}
schemas["UserResponse"] = {
    "type": "object",
    "description": "用户完整信息（不含密码）",
    "properties": {
        "id": uuid_prop(),
        "username": prop("string"),
        "email": prop("string", format="email"),
        "nickname": prop("string", nullable=True),
        "status": prop("string", "用户状态", enum=["active", "disabled", "pending"]),
        "roles": {"type": "array", "items": prop("string"), "description": "角色名称列表"},
        "role_labels": {"type": "array", "items": prop("string"), "description": "角色显示名列表"},
        "permissions": {"type": "array", "items": prop("string"), "description": "权限标识列表，如 kb:read"},
        "department": prop("string", "所属部门编码", nullable=True),
        "is_super_admin": prop("boolean"),
        "created_at": dt_prop(),
        "last_login_at": dt_prop(nullable=True),
    },
}

# ---- 用户管理 ----
schemas["AdminCreateUserRequest"] = {
    "type": "object",
    "required": ["username", "password", "email"],
    "properties": {
        "username": prop("string", minLength=3, maxLength=50),
        "password": prop("string", minLength=8, maxLength=128),
        "email": prop("string", format="email"),
        "nickname": prop("string", maxLength=100, nullable=True),
        "role_ids": {"type": "array", "items": uuid_prop(), "default": [], "description": "角色 UUID 列表"},
    },
}
schemas["UserStatusRequest"] = {
    "type": "object",
    "required": ["status"],
    "properties": {"status": prop("string", enum=["active", "disabled", "pending"])},
}
schemas["UserRolesRequest"] = {
    "type": "object",
    "required": ["role_ids"],
    "properties": {"role_ids": {"type": "array", "items": uuid_prop(), "description": "全量覆盖"}},
}

# ---- 角色 ----
schemas["RoleRequest"] = {
    "type": "object",
    "required": ["name"],
    "properties": {
        "name": prop("string", minLength=2, maxLength=100),
        "description": prop("string", nullable=True),
        "is_enabled": prop("boolean", default=True),
        "permission_codes": {"type": "array", "items": prop("string"), "default": [], "example": ["kb:read", "qa:ask"]},
    },
}
schemas["RolePermissionsRequest"] = {
    "type": "object",
    "required": ["permission_codes"],
    "properties": {"permission_codes": {"type": "array", "items": prop("string"), "description": "全量覆盖"}},
}
schemas["RoleResponse"] = {
    "type": "object",
    "properties": {
        "id": uuid_prop(),
        "name": prop("string"),
        "display_name": prop("string"),
        "description": prop("string", nullable=True),
        "is_builtin": prop("boolean"),
        "is_enabled": prop("boolean"),
        "permissions": {"type": "array", "items": prop("string")},
    },
}
schemas["PermissionItem"] = {
    "type": "object",
    "properties": {
        "code": prop("string", example="kb:read"),
        "name": prop("string"),
        "scope": prop("string", enum=["global", "kb_scoped"]),
    },
}

# ---- 部门 ----
schemas["DepartmentCreate"] = {
    "type": "object",
    "required": ["code", "name"],
    "properties": {
        "code": prop("string", "部门编码，如 A / B / GUEST", minLength=1, maxLength=50),
        "name": prop("string", minLength=1, maxLength=100),
        "description": prop("string", nullable=True),
        "is_enabled": prop("boolean", default=True),
    },
}
schemas["DepartmentUpdate"] = {
    "type": "object",
    "properties": {
        "code": prop("string", minLength=1, maxLength=50, nullable=True),
        "name": prop("string", minLength=1, maxLength=100, nullable=True),
        "description": prop("string", nullable=True),
        "is_enabled": prop("boolean", nullable=True),
    },
}
schemas["DepartmentMembersRequest"] = {
    "type": "object",
    "required": ["user_ids"],
    "properties": {"user_ids": {"type": "array", "minItems": 1, "items": uuid_prop()}},
}
schemas["DepartmentKbsRequest"] = {
    "type": "object",
    "required": ["kb_ids"],
    "properties": {"kb_ids": {"type": "array", "minItems": 1, "items": uuid_prop()}},
}
schemas["DepartmentMemberBrief"] = {
    "type": "object",
    "properties": {
        "id": uuid_prop(),
        "username": prop("string"),
        "nickname": prop("string", nullable=True),
        "email": prop("string", nullable=True),
        "status": prop("string", nullable=True),
    },
}
schemas["DepartmentKbBrief"] = {
    "type": "object",
    "properties": {
        "id": uuid_prop(),
        "name": prop("string"),
        "status": prop("string", nullable=True),
        "visibility": prop("string", nullable=True),
        "doc_count": prop("integer", nullable=True),
    },
}
schemas["DepartmentListItem"] = {
    "type": "object",
    "properties": {
        "id": uuid_prop(),
        "code": prop("string"),
        "name": prop("string"),
        "description": prop("string", nullable=True),
        "is_enabled": prop("boolean"),
        "member_count": prop("integer"),
        "kb_count": prop("integer"),
        "created_at": dt_prop(),
        "updated_at": dt_prop(),
    },
}
schemas["DepartmentDetail"] = {
    "allOf": [
        ref("DepartmentListItem"),
        {
            "type": "object",
            "properties": {
                "members": {"type": "array", "items": ref("DepartmentMemberBrief")},
                "knowledge_bases": {"type": "array", "items": ref("DepartmentKbBrief")},
            },
        },
    ]
}

# ---- 大模型 ----
_MODEL_TYPES = ["llm", "embedding", "rerank"]
schemas["CreateModelConfigRequest"] = {
    "type": "object",
    "required": ["name", "model_type", "provider", "model_name"],
    "properties": {
        "name": prop("string", minLength=1, maxLength=100),
        "model_type": prop("string", enum=_MODEL_TYPES),
        "provider": prop("string", minLength=1, maxLength=50, example="openai"),
        "model_name": prop("string", minLength=1, maxLength=200, example="qwen3.7-plus"),
        "base_url": prop("string", maxLength=500, nullable=True),
        "config": prop("object", "如 temperature / max_tokens", default={}),
        "timeout_seconds": prop("integer", minimum=5, maximum=600, default=60),
        "api_key_env": prop("string", "密钥所在环境变量名（不存明文）", maxLength=100, nullable=True),
        "is_default": prop("boolean", default=False),
        "is_enabled": prop("boolean", default=True),
        "priority": prop("integer", "值越小优先级越高", minimum=0, maximum=10000, default=100),
    },
}
schemas["UpdateModelConfigRequest"] = {
    "type": "object",
    "properties": {
        "name": prop("string", maxLength=100, nullable=True),
        "provider": prop("string", maxLength=50, nullable=True),
        "model_name": prop("string", maxLength=200, nullable=True),
        "base_url": prop("string", maxLength=500, nullable=True),
        "config": prop("object", nullable=True),
        "timeout_seconds": prop("integer", minimum=5, maximum=600, nullable=True),
        "api_key_env": prop("string", maxLength=100, nullable=True),
        "priority": prop("integer", minimum=0, maximum=10000, nullable=True),
        "is_enabled": prop("boolean", nullable=True),
        "is_default": prop("boolean", nullable=True),
    },
}
schemas["ModelStatusRequest"] = {
    "type": "object",
    "required": ["is_enabled"],
    "properties": {"is_enabled": prop("boolean")},
}
schemas["SetDefaultRequest"] = {
    "type": "object",
    "properties": {"is_default": prop("boolean", default=True)},
}
schemas["ModelConfigResponse"] = {
    "type": "object",
    "description": "不含密钥明文；has_api_key 表示对应环境变量是否已配置",
    "properties": {
        "id": uuid_prop(),
        "name": prop("string"),
        "model_type": prop("string", enum=_MODEL_TYPES),
        "provider": prop("string"),
        "model_name": prop("string"),
        "base_url": prop("string", nullable=True),
        "is_default": prop("boolean"),
        "is_enabled": prop("boolean"),
        "priority": prop("integer", default=100),
        "config": prop("object"),
        "timeout_seconds": prop("integer"),
        "api_key_env": prop("string", nullable=True),
        "has_api_key": prop("boolean", default=False),
        "created_at": dt_prop(),
        "updated_at": dt_prop(),
    },
}
schemas["ModelUsageDaily"] = {
    "type": "object",
    "properties": {
        "date": prop("string"),
        "observations": prop("integer"),
        "input_tokens": prop("integer"),
        "output_tokens": prop("integer"),
        "total_tokens": prop("integer"),
        "cost": prop("number"),
    },
}
schemas["ModelUsageItem"] = {
    "type": "object",
    "properties": {
        "model": prop("string"),
        "total_traces": prop("integer"),
        "total_observations": prop("integer"),
        "input_tokens": prop("integer"),
        "output_tokens": prop("integer"),
        "total_tokens": prop("integer"),
        "total_cost": prop("number"),
        "daily": {"type": "array", "items": ref("ModelUsageDaily")},
    },
}
schemas["ModelUsageResponse"] = {
    "type": "object",
    "description": "Langfuse 模型用量聚合",
    "properties": {
        "enabled": prop("boolean", "是否已配置 Langfuse 密钥"),
        "host": prop("string"),
        "range": {
            "type": "object",
            "properties": {"from": dt_prop(), "to": dt_prop(), "days": prop("integer")},
        },
        "totals": {
            "type": "object",
            "properties": {
                "total_traces": prop("integer"),
                "total_observations": prop("integer"),
                "input_tokens": prop("integer"),
                "output_tokens": prop("integer"),
                "total_tokens": prop("integer"),
                "total_cost": prop("number"),
            },
        },
        "models": {"type": "array", "items": ref("ModelUsageItem")},
        "notice": prop("string", "限流/缓存降级提示", nullable=True),
    },
}

# ---- 知识库 ----
_KB_TYPES = ["technical", "product", "faq", "general"]
_SPLIT_MODES = ["fixed", "sliding", "paragraph", "heading"]
schemas["KnowledgeBaseCreate"] = {
    "type": "object",
    "required": ["name", "type", "embedding_model"],
    "properties": {
        "name": prop("string", example="技术文档库"),
        "type": prop("string", "知识库类型", enum=_KB_TYPES),
        "tags": {"type": "array", "items": prop("string"), "default": []},
        "description": prop("string", nullable=True),
        "department": prop(
            "string",
            "访问控制核心：GUEST=访客/全员可见；具体部门=部门隔离；留空=仅创建者/授权者",
            nullable=True,
        ),
        "visibility": prop(
            "string",
            "由 department 派生（GUEST→public，其余→restricted），一般无需手动传",
            enum=["public", "restricted"],
            nullable=True,
        ),
        "embedding_model": prop("string", example="text-embedding-v3"),
        "chunk_size": prop("integer", minimum=100, maximum=5000, default=500),
        "chunk_overlap": prop("integer", minimum=0, maximum=1000, default=50),
    },
}
schemas["KnowledgeBaseUpdate"] = {
    "type": "object",
    "properties": {
        "name": prop("string", nullable=True),
        "type": prop("string", enum=_KB_TYPES, nullable=True),
        "tags": {"type": "array", "items": prop("string"), "nullable": True},
        "description": prop("string", nullable=True),
        "department": prop("string", "变更部门会重新派生可见性", nullable=True),
        "visibility": prop("string", "传入将被忽略并按 department 重算", nullable=True),
        "embedding_model": prop("string", nullable=True),
        "chunk_size": prop("integer", minimum=100, maximum=5000, nullable=True),
        "chunk_overlap": prop("integer", minimum=0, maximum=1000, nullable=True),
    },
}
schemas["KnowledgeBaseResponse"] = {
    "type": "object",
    "properties": {
        "id": uuid_prop(),
        "name": prop("string"),
        "type": prop("string"),
        "tags": {"type": "array", "items": prop("string")},
        "description": prop("string", nullable=True),
        "visibility": prop("string", enum=["public", "restricted"]),
        "department": prop("string", nullable=True),
        "embedding_model": prop("string"),
        "chunk_size": prop("integer"),
        "chunk_overlap": prop("integer"),
        "status": prop("string", enum=["active", "vectorizing", "archived", "deleted"]),
        "current_index_version": prop("string", "唯一被检索的索引版本；空表示不可检索", nullable=True),
        "document_count": prop("integer", default=0),
        "chunk_count": prop("integer", default=0),
        "creator_id": uuid_prop(),
        "created_at": dt_prop(),
        "updated_at": dt_prop(),
    },
}
schemas["ReVectorizeRequest"] = {
    "type": "object",
    "properties": {
        "chunk_size": prop("integer", minimum=100, maximum=5000, nullable=True),
        "chunk_overlap": prop("integer", minimum=0, maximum=1000, nullable=True),
        "split_mode": prop("string", enum=_SPLIT_MODES, nullable=True),
        "separators": {"type": "array", "items": prop("string"), "nullable": True},
        "embedding_model": prop("string", maxLength=200, nullable=True),
        "apply_to_documents": prop("boolean", default=True),
        "force_all": prop("boolean", default=False),
    },
}
schemas["VectorizeStatusResponse"] = {
    "type": "object",
    "properties": {
        "task_id": uuid_prop(),
        "kb_id": uuid_prop(),
        "status": prop("string", "任务状态"),
        "progress": prop("integer", default=0, example=45),
        "processed_count": prop("integer", default=0),
        "total_count": prop("integer", default=0),
        "error_message": prop("string", nullable=True),
        "started_at": dt_prop(nullable=True),
        "completed_at": dt_prop(nullable=True),
        "target_version": prop("string", nullable=True),
    },
}
schemas["KBPermissionItem"] = {
    "type": "object",
    "required": ["permission"],
    "properties": {
        "user_id": uuid_prop("与 role_id 至少一个", nullable=True),
        "role_id": uuid_prop("与 user_id 至少一个", nullable=True),
        "permission": prop("string", example="kb:upload"),
    },
}
schemas["KBPermissionUpdate"] = {
    "type": "object",
    "required": ["permissions"],
    "properties": {
        "permissions": {"type": "array", "items": ref("KBPermissionItem"), "description": "全量覆盖"}
    },
}

# ---- 文档 ----
_DOC_STATUS = "uploaded/parsing/processing/pending_segment/vectorizing/ready/error/archived"
schemas["DocumentResponse"] = {
    "type": "object",
    "properties": {
        "id": uuid_prop(),
        "kb_id": uuid_prop(),
        "filename": prop("string"),
        "file_type": prop("string"),
        "file_size": prop("integer"),
        "file_path": prop("string", "MinIO 对象路径"),
        "chunk_count": prop("integer"),
        "status": prop("string", _DOC_STATUS),
        "error_message": prop("string", nullable=True),
        "creator_id": uuid_prop(),
        "created_at": dt_prop(),
        "updated_at": dt_prop(),
    },
}
schemas["DocumentListItem"] = {
    "type": "object",
    "properties": {
        "id": uuid_prop(),
        "filename": prop("string"),
        "file_type": prop("string"),
        "file_size": prop("integer"),
        "chunk_count": prop("integer"),
        "status": prop("string"),
        "created_at": dt_prop(),
    },
}
schemas["DocumentContentPreviewResponse"] = {
    "type": "object",
    "properties": {
        "id": uuid_prop(),
        "kb_id": uuid_prop(),
        "filename": prop("string"),
        "file_type": prop("string"),
        "status": prop("string"),
        "chunk_count": prop("integer"),
        "error_message": prop("string", nullable=True),
        "raw_text": prop("string"),
        "normalized_text": prop("string"),
        "raw_char_count": prop("integer"),
        "normalized_char_count": prop("integer"),
        "truncated": prop("boolean"),
        "max_preview_chars": prop("integer", default=80000),
        "preview_source": prop("string"),
        "segment_rules": prop("object"),
    },
}
schemas["UpdateSegmentRulesRequest"] = {
    "type": "object",
    "required": ["chunk_size", "chunk_overlap"],
    "properties": {
        "chunk_size": prop("integer", minimum=100, maximum=5000),
        "chunk_overlap": prop("integer", minimum=0, maximum=1000),
        "separators": {"type": "array", "items": prop("string"), "nullable": True},
        "split_mode": prop("string", enum=_SPLIT_MODES, nullable=True),
        "enable_semantic": prop("boolean", default=False, nullable=True),
    },
}
schemas["DocumentChunkResponse"] = {
    "type": "object",
    "properties": {
        "id": uuid_prop(),
        "document_id": uuid_prop(),
        "chunk_index": prop("integer"),
        "content": prop("string"),
        "char_count": prop("integer"),
        "metadata": prop("object"),
        "is_enabled": prop("boolean", "禁用后不参与检索与引用", default=True),
    },
}
schemas["UpdateChunkRequest"] = {
    "type": "object",
    "properties": {
        "content": prop("string", nullable=True),
        "is_enabled": prop("boolean", nullable=True),
        "metadata": prop("object", nullable=True),
    },
}
schemas["SegmentPreviewChunk"] = {
    "type": "object",
    "properties": {
        "chunk_index": prop("integer"),
        "content": prop("string"),
        "char_count": prop("integer"),
        "metadata": prop("object"),
    },
}
schemas["SegmentPreviewResponse"] = {
    "type": "object",
    "properties": {
        "document_id": uuid_prop(),
        "rules": prop("object"),
        "total_chunks": prop("integer"),
        "chunks": {"type": "array", "items": ref("SegmentPreviewChunk")},
        "preview_source": prop("string"),
    },
}
schemas["FileSegmentPreviewResponse"] = {
    "type": "object",
    "properties": {
        "kb_id": uuid_prop(),
        "document_id": uuid_prop(nullable=True),
        "filename": prop("string"),
        "file_type": prop("string"),
        "rules": prop("object"),
        "total_chunks": prop("integer"),
        "total_chars": prop("integer"),
        "chunks": {
            "type": "array",
            "items": {
                "allOf": [
                    ref("SegmentPreviewChunk"),
                    {"type": "object", "properties": {"start": prop("integer"), "end": prop("integer")}},
                ]
            },
        },
        "preview_source": prop("string"),
    },
}
schemas["NormalizeResult"] = {
    "type": "object",
    "properties": {
        "removed_blank_lines": prop("integer", default=0),
        "removed_duplicate_blocks": prop("integer", default=0),
        "char_count_before": prop("integer", default=0),
        "char_count_after": prop("integer", default=0),
    },
}

# ---- 问答 ----
_STRATEGIES = ["vector", "fulltext", "hybrid"]
schemas["AskRequest"] = {
    "type": "object",
    "required": ["question"],
    "properties": {
        "question": prop("string", minLength=1, maxLength=2000, example="如何配置知识库权限？"),
        "session_id": uuid_prop(
            "可选。不传则始终新建会话（不按 X-Guest-Id / Redis 自动复用旧会话）；"
            "传入已有会话 ID 可多轮续聊（含已闲置过期的会话，会重新激活）",
            nullable=True,
        ),
        "kb_ids": {
            "type": "array",
            "items": uuid_prop(),
            "nullable": True,
            "description": "限定检索知识库；默认全部可访问范围（取交集）",
        },
        "strategy": prop("string", enum=_STRATEGIES, default="hybrid"),
        "top_k": prop("integer", minimum=1, maximum=20, default=5),
        "temperature": prop("number", minimum=0, maximum=2, default=0.7),
    },
}
schemas["CitationResponse"] = {
    "type": "object",
    "properties": {
        "doc_id": uuid_prop(),
        "doc_name": prop("string"),
        "chunk_index": prop("integer"),
        "content": prop("string"),
        "score": prop("number"),
    },
}
schemas["AskEventResponse"] = {
    "type": "object",
    "description": "SSE 单条事件 data 结构（event 名在 SSE 帧的 event: 行）",
    "properties": {
        "event": prop(
            "string",
            enum=[
                "intent",
                "guard_blocked",
                "query_processing",
                "cache_hit",
                "chunk",
                "citations",
                "done",
                "error",
            ],
        ),
        "content": prop("string", "chunk 事件的增量文本", nullable=True),
        "items": {"type": "array", "items": ref("CitationResponse"), "nullable": True},
        "citations": {"type": "array", "items": ref("CitationResponse"), "nullable": True},
        "session_id": uuid_prop(nullable=True),
        "message_id": uuid_prop(nullable=True),
        "request_id": prop("string", nullable=True),
        "confidence": prop("string", enum=["high", "medium", "low"], nullable=True),
        "confidence_score": prop(
            "number",
            "done 事件数值置信度，范围 0~1；无法计算时为 -1",
            nullable=True,
        ),
        "performance": {
            "type": "object",
            "nullable": True,
            "additionalProperties": True,
            "description": "done 事件可选性能字段（各阶段耗时等）",
        },
        "message": prop("string", "error 事件错误信息", nullable=True),
    },
}
schemas["SessionResponse"] = {
    "type": "object",
    "properties": {
        "id": uuid_prop(),
        "title": prop("string"),
        "kb_names": {"type": "array", "items": prop("string")},
        "message_count": prop("integer"),
        "created_at": dt_prop(),
        "updated_at": dt_prop(),
    },
}
schemas["MessageResponse"] = {
    "type": "object",
    "properties": {
        "id": uuid_prop(),
        "role": prop("string", enum=["user", "assistant", "system"]),
        "content": prop("string"),
        "citations": {"type": "array", "items": ref("CitationResponse"), "nullable": True},
        "token_count": prop("integer", nullable=True),
        "created_at": dt_prop(),
        "request_id": prop("string", nullable=True),
        "strategy": prop("string", nullable=True),
        "latency_ms": prop("integer", nullable=True),
    },
}
schemas["RenameSessionRequest"] = {
    "type": "object",
    "required": ["title"],
    "properties": {"title": prop("string", minLength=1, maxLength=100)},
}
schemas["FeedbackRequest"] = {
    "type": "object",
    "required": ["message_id", "rating"],
    "properties": {
        "message_id": uuid_prop(),
        "rating": prop("string", enum=["useful", "useless"]),
        "comment": prop("string", maxLength=500, nullable=True),
    },
}

# ---- 命中率测试 ----
schemas["TestQuestion"] = {
    "type": "object",
    "required": ["question"],
    "properties": {
        "question": prop("string"),
        "expected_doc_ids": {"type": "array", "items": uuid_prop(), "nullable": True},
        "expected_chunk_ids": {"type": "array", "items": uuid_prop(), "nullable": True},
    },
}
schemas["CreateTestCaseRequest"] = {
    "type": "object",
    "required": ["name", "questions"],
    "properties": {
        "name": prop("string"),
        "description": prop("string", nullable=True),
        "questions": {"type": "array", "items": ref("TestQuestion")},
    },
}
schemas["UpdateTestCaseRequest"] = {
    "type": "object",
    "properties": {
        "name": prop("string", nullable=True),
        "description": prop("string", nullable=True),
        "questions": {"type": "array", "items": ref("TestQuestion"), "nullable": True},
    },
}
schemas["TestCaseResponse"] = {
    "type": "object",
    "properties": {
        "id": uuid_prop(),
        "name": prop("string"),
        "description": prop("string", nullable=True),
        "question_count": prop("integer"),
        "questions": {"type": "array", "items": ref("TestQuestion")},
        "created_at": dt_prop(),
    },
}
schemas["TestRunRequest"] = {
    "type": "object",
    "required": ["kb_ids", "strategy"],
    "properties": {
        "case_id": uuid_prop("不传则用 questions 做临时测试", nullable=True),
        "kb_ids": {"type": "array", "minItems": 1, "items": uuid_prop()},
        "doc_ids": {"type": "array", "items": uuid_prop(), "nullable": True},
        "strategy": prop("string", enum=_STRATEGIES),
        "top_k": prop("integer", minimum=1, maximum=20, default=5),
        "similarity_threshold": prop("number", minimum=0, maximum=1, default=0.5),
        "questions": {"type": "array", "items": prop("string"), "nullable": True},
    },
}
schemas["CompareTestRequest"] = {
    "type": "object",
    "required": ["case_id", "kb_ids"],
    "properties": {
        "case_id": uuid_prop(),
        "kb_ids": {"type": "array", "minItems": 1, "items": uuid_prop()},
        "doc_ids": {"type": "array", "items": uuid_prop(), "nullable": True},
        "strategies": {
            "type": "array",
            "minItems": 2,
            "items": prop("string", enum=_STRATEGIES),
            "description": "默认三种策略",
        },
        "top_k": prop("integer", minimum=1, maximum=20, default=5),
        "similarity_threshold": prop("number", minimum=0, maximum=1, default=0.5),
    },
}
schemas["TestRunResponse"] = {
    "type": "object",
    "properties": {
        "id": uuid_prop(),
        "case_id": uuid_prop(nullable=True),
        "kb_ids": {"type": "array", "items": uuid_prop()},
        "strategy": prop("string"),
        "top_k": prop("integer"),
        "status": prop("string", enum=["running", "completed", "failed"]),
        "total_questions": prop("integer"),
        "hit_count": prop("integer"),
        "hit_rate": prop("number", "命中率 = hit_count / total_questions", nullable=True),
        "score": prop(
            "number",
            "综合得分：各题命中片段相关度的算术平均（0–1）；无命中时为 0",
            nullable=True,
        ),
        "recall_at_k": prop("number", nullable=True),
        "mrr": prop("number", nullable=True),
        "avg_elapsed_ms": prop("number", nullable=True),
        "created_at": dt_prop(nullable=True),
        "completed_at": dt_prop(nullable=True),
    },
}
schemas["TestResultResponse"] = {
    "type": "object",
    "properties": {
        "id": uuid_prop(),
        "question": prop("string"),
        "is_hit": prop("boolean"),
        "hit_rank": prop("integer", nullable=True),
        "score": prop("number", nullable=True),
        "strategy": prop("string"),
        "elapsed_ms": prop("integer", nullable=True),
        "actual_chunks": {"type": "array", "items": prop("string")},
    },
}
schemas["TestRunDetail"] = {
    "type": "object",
    "properties": {
        "run": ref("TestRunResponse"),
        "results": {"type": "array", "items": ref("TestResultResponse")},
    },
}
schemas["CompareTestResponse"] = {
    "type": "object",
    "properties": {
        "case_id": uuid_prop(),
        "runs": {"type": "array", "items": ref("TestRunResponse")},
        "side_by_side": {"type": "array", "items": prop("object")},
    },
}

# ---- 快照 ----
schemas["CreateSnapshotRequest"] = {
    "type": "object",
    "required": ["name"],
    "properties": {
        "name": prop("string", minLength=1, maxLength=200),
        "description": prop("string", maxLength=2000, nullable=True),
    },
}
schemas["SnapshotListItem"] = {
    "type": "object",
    "properties": {
        "id": uuid_prop(),
        "kb_id": uuid_prop(),
        "name": prop("string"),
        "description": prop("string", nullable=True),
        "trigger": prop("string", "auto_* / manual / rollback_protection"),
        "status": prop("string", enum=["active", "deleted"]),
        "document_count": prop("integer", default=0),
        "total_chunks": prop("integer", default=0),
        "creator_id": uuid_prop(),
        "created_at": dt_prop(),
    },
}
schemas["SnapshotResponse"] = {
    "allOf": [
        ref("SnapshotListItem"),
        {
            "type": "object",
            "properties": {"config_snapshot": prop("object"), "updated_at": dt_prop(nullable=True)},
        },
    ]
}
schemas["SnapshotDetailResponse"] = {
    "allOf": [
        ref("SnapshotResponse"),
        {
            "type": "object",
            "properties": {
                "documents": {"type": "array", "items": prop("object")},
                "permission_snapshot": {"type": "array", "items": prop("object")},
                "segment_rules": prop("object"),
            },
        },
    ]
}
schemas["RollbackRequest"] = {
    "type": "object",
    "required": ["confirm"],
    "properties": {
        "confirm": prop("boolean", "必须为 true 才执行回退", example=True),
        "document_ids": {"type": "array", "items": uuid_prop(), "nullable": True, "description": "选择性回退"},
    },
}
schemas["RollbackPreviewResponse"] = {
    "type": "object",
    "properties": {
        "snapshot_id": uuid_prop(),
        "kb_id": uuid_prop(),
        "snapshot_name": prop("string"),
        "affected_documents": {"type": "array", "items": prop("object")},
        "config_changes": prop("object"),
        "total_changes": prop("integer"),
        "will_create_protection_snapshot": prop("boolean"),
        "rebuild_required": prop("boolean"),
    },
}
schemas["RollbackResultResponse"] = {
    "type": "object",
    "properties": {
        "protection_snapshot_id": uuid_prop(),
        "new_index_version": prop("string"),
        "index_status": prop("string", example="building"),
        "before_version": prop("string", nullable=True),
        "after_version": prop("string"),
        "restored_document_count": prop("integer"),
        "restored_document_ids": {"type": "array", "items": uuid_prop()},
        "selective": prop("boolean", default=False),
        "rebuild_required": prop("boolean", default=True),
        "message": prop("string"),
    },
}
schemas["SnapshotCleanupResponse"] = {
    "type": "object",
    "properties": {
        "expired_deleted": prop("integer"),
        "excess_deleted": prop("integer"),
        "retention_days": prop("integer"),
        "max_count": prop("integer"),
        "active_remaining": prop("integer"),
    },
}

# ---- 审计 ----
schemas["AuditLogListItem"] = {
    "type": "object",
    "properties": {
        "id": uuid_prop(),
        "user_id": uuid_prop(nullable=True),
        "user_name": prop("string", nullable=True),
        "action": prop("string", example="kb.create"),
        "resource_type": prop("string"),
        "resource_id": prop("string", nullable=True),
        "result": prop("string", enum=["success", "failure"], default="success"),
        "request_id": prop("string", nullable=True),
        "created_at": dt_prop(),
    },
}
schemas["AuditLogResponse"] = {
    "allOf": [
        ref("AuditLogListItem"),
        {
            "type": "object",
            "properties": {
                "detail": prop("object", "变更前后对比", nullable=True),
                "ip_address": prop("string", nullable=True),
                "user_agent": prop("string", nullable=True),
                "error_message": prop("string", nullable=True),
                "updated_at": dt_prop(nullable=True),
            },
        },
    ]
}
schemas["AuditBatchDeleteRequest"] = {
    "type": "object",
    "required": ["ids"],
    "properties": {
        "ids": {
            "type": "array",
            "minItems": 1,
            "maxItems": 200,
            "items": {"type": "string", "format": "uuid"},
            "description": "要删除的审计日志 ID 列表",
        },
    },
}
schemas["AuditBatchDeleteResult"] = {
    "type": "object",
    "required": ["deleted"],
    "properties": {
        "deleted": prop("integer", "实际删除条数"),
    },
}

# ---- 监控 ----
schemas["HealthResponse"] = {
    "type": "object",
    "properties": {
        "status": prop("string", enum=["healthy", "degraded", "unhealthy"]),
        "version": prop("string", example="2.1.0"),
        "uptime_seconds": prop("integer", description="进程已运行秒数"),
        "checks": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {"status": prop("string"), "latency_ms": prop("number")},
            },
            "description": "各组件连通性：postgres/redis/chroma/langfuse/minio",
        },
    },
}
schemas["SystemStatsResponse"] = {
    "type": "object",
    "properties": {
        "user_count": prop("integer"),
        "kb_count": prop("integer"),
        "doc_count": prop("integer"),
        "active_sessions": prop(
            "integer",
            description="status=active 的问答会话数（不含 expired/deleted）",
        ),
        "task_queue_size": prop("integer"),
        "qa_trend_7d": {
            "type": "array",
            "items": {"type": "integer"},
            "minItems": 7,
            "maxItems": 7,
            "description": "近 7 天每日用户提问数（含今天，升序）",
        },
        "hit_rate_trend_7d": {
            "type": "array",
            "items": {"type": "number"},
            "minItems": 7,
            "maxItems": 7,
            "description": "近 7 天每日命中率 0–1（含今天，升序）",
        },
        "qa_trend_30d": {
            "type": "array",
            "items": {"type": "integer"},
            "minItems": 30,
            "maxItems": 30,
            "description": "近 30 天每日用户提问数（含今天，升序）",
        },
        "hit_rate_trend_30d": {
            "type": "array",
            "items": {"type": "number"},
            "minItems": 30,
            "maxItems": 30,
            "description": "近 30 天每日命中率 0–1（含今天，升序）",
        },
        "error_24h": {
            "type": "array",
            "items": {"type": "integer"},
            "minItems": 4,
            "maxItems": 4,
            "description": "近 24 小时错误量（4 个等宽时段，旧→新）",
        },
        "error_hourly_48h": {
            "type": "array",
            "items": {"type": "integer"},
            "minItems": 48,
            "maxItems": 48,
            "description": "近 48 小时每小时错误量（文档失败+向量化失败，旧→新）",
        },
        "guard_blocked_24h": prop("integer", "最近 24 小时 Guard 阻拦次数", default=0),
        "guard_blocked_7d": prop("integer", "最近 7 天 Guard 阻拦次数", default=0),
        "guard_recent_events": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": True},
            "description": "最近阻拦摘要；完整列表见 /monitor/guard-events",
        },
    },
}
schemas["GuardBlockedEventItem"] = {
    "type": "object",
    "properties": {
        "id": prop("string"),
        "created_at": prop("string", format="date-time"),
        "intent": prop("string"),
        "reason_code": prop("string"),
        "detector": prop("string"),
        "confidence": prop("number"),
        "actor_label": prop("string", "注册用户名或「访客」"),
        "client_ip": prop("string", nullable=True),
        "user_id": uuid_prop(nullable=True),
        "is_registered": prop("boolean"),
        "question_preview": prop("string", "脱敏短摘要", nullable=True),
    },
}
schemas["GuardBlockedEventListResponse"] = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": ref("GuardBlockedEventItem")},
        "total": prop("integer"),
        "page": prop("integer"),
        "page_size": prop("integer"),
        "blocked_24h": prop("integer"),
        "blocked_7d": prop("integer"),
    },
}

# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

paths: dict = {}

# ---- 认证 ----
paths["/auth/register"] = {
    "post": op(
        "用户注册",
        "公开接口。创建账号后默认为 guest（访客）角色；密码服务端 bcrypt 哈希存储。",
        ["认证"],
        public=True,
        request_body=json_body("RegisterRequest"),
        responses={**resp("注册成功", ref("UserResponse"), 201), **err_resps(400, 409, 422, 500)},
    )
}
paths["/auth/login"] = {
    "post": op(
        "用户登录",
        "公开接口。校验用户名密码，返回 access/refresh JWT。凭证错误返回 401（文案：用户名或密码错误）；禁用用户返回 403。",
        ["认证"],
        public=True,
        request_body=json_body("LoginRequest"),
        responses={**resp("登录成功", ref("TokenResponse")), **err_resps(400, 401, 403, 422, 500)},
    )
}
paths["/auth/refresh"] = {
    "post": op(
        "刷新 Token",
        "使用 refresh_token 换取新的 Token 对。",
        ["认证"],
        public=True,
        request_body=json_body("RefreshRequest"),
        responses={**resp("刷新成功", ref("TokenResponse")), **err_resps(401, 422, 500)},
    )
}
paths["/auth/me"] = {
    "get": op(
        "当前用户信息",
        "返回当前登录用户资料、角色、权限与部门，供前端渲染菜单与按钮。",
        ["认证"],
        responses={**resp("成功", ref("UserResponse")), **err_resps(401, 500)},
    ),
    "put": op(
        "修改本人资料",
        "更新昵称/邮箱/部门。",
        ["认证"],
        request_body=json_body("UserUpdateRequest"),
        responses={**resp("成功", ref("UserResponse")), **err_resps(401, 422, 500)},
    ),
}
paths["/auth/change-password"] = {
    "post": op(
        "修改本人密码",
        "需提供原密码，并两次确认新密码。固定超管账号 super 禁止调用，仅可通过 .env 的 SUPER_ADMIN_PASSWORD 维护。",
        ["认证"],
        request_body=json_body("ChangePasswordRequest"),
        responses={**resp("成功"), **err_resps(400, 401, 403, 422, 500)},
    ),
}

# ---- 用户管理 ----
paths["/users"] = {
    "post": op(
        "创建用户",
        "管理端创建用户并绑定角色。需要 user:write。",
        ["用户管理"],
        request_body=json_body("AdminCreateUserRequest"),
        responses={**resp("创建成功", ref("UserResponse"), 201), **err_resps(400, 401, 403, 409, 422, 500)},
    ),
    "get": op(
        "用户列表",
        "分页查询用户，支持 keyword（用户名/邮箱）与 status 过滤。需要 user:read。",
        ["用户管理"],
        parameters=page_params()
        + [
            q("keyword", "搜索关键字", {"type": "string"}),
            q("status", "用户状态", {"type": "string", "enum": ["active", "disabled", "pending"]}),
        ],
        responses={**resp("成功", page_of(ref("UserResponse"))), **err_resps(401, 403, 500)},
    ),
}
paths["/users/{id}"] = {
    "get": op(
        "用户详情",
        "按 ID 获取用户完整信息。需要 user:read。",
        ["用户管理"],
        parameters=[path_param()],
        responses={**resp("成功", ref("UserResponse")), **err_resps(401, 403, 404, 500)},
    ),
    "put": op(
        "修改用户信息",
        "更新昵称/邮箱/部门。需要 user:write。",
        ["用户管理"],
        parameters=[path_param()],
        request_body=json_body("UserUpdateRequest"),
        responses={**resp("成功", ref("UserResponse")), **err_resps(400, 401, 403, 404, 422, 500)},
    ),
    "delete": op(
        "删除用户",
        "删除权限严格低于自己的用户；不可删除自己或同级/更高级用户。需要 user:write。",
        ["用户管理"],
        parameters=[path_param()],
        responses={**resp("删除成功"), **err_resps(400, 401, 403, 404, 500)},
    ),
}
paths["/users/{id}/status"] = {
    "patch": op(
        "启用/禁用用户",
        "仅可操作权限低于自己的用户；不可操作自己。需要 user:write。",
        ["用户管理"],
        parameters=[path_param()],
        request_body=json_body("UserStatusRequest"),
        responses={**resp("成功", ref("UserResponse")), **err_resps(400, 401, 403, 404, 422, 500)},
    )
}
paths["/users/{id}/roles"] = {
    "put": op(
        "修改用户角色",
        "全量覆盖角色绑定。仅可变更权限低于自己的用户。"
        "超管可分配 admin/super_admin；普通管理员不可将他人设为管理员或超管。需要 user:write。",
        ["用户管理"],
        parameters=[path_param()],
        request_body=json_body("UserRolesRequest"),
        responses={**resp("成功", ref("UserResponse")), **err_resps(401, 403, 404, 422, 500)},
    )
}

# ---- 角色 ----
paths["/roles"] = {
    "get": op(
        "角色列表",
        "分页列出角色。需要 role:read。",
        ["角色管理"],
        parameters=page_params(),
        responses={**resp("成功", page_of(ref("RoleResponse"))), **err_resps(401, 403, 500)},
    ),
    "post": op(
        "创建角色",
        "创建自定义角色并绑定权限标识。需要 role:write。",
        ["角色管理"],
        request_body=json_body("RoleRequest"),
        responses={**resp("创建成功", ref("RoleResponse"), 201), **err_resps(400, 401, 403, 409, 422, 500)},
    ),
}
paths["/roles/permissions"] = {
    "get": op(
        "权限清单",
        "返回全部可分配权限标识 [{code,name,scope}]。需要 role:read。",
        ["角色管理"],
        responses={
            **resp("成功", {"type": "array", "items": ref("PermissionItem")}),
            **err_resps(401, 403, 500),
        },
    )
}
paths["/roles/{id}"] = {
    "put": op(
        "修改角色",
        "修改名称/描述/启停。内置角色不可改名。需要 role:write。",
        ["角色管理"],
        parameters=[path_param()],
        request_body=json_body("RoleRequest"),
        responses={**resp("成功", ref("RoleResponse")), **err_resps(401, 403, 404, 409, 422, 500)},
    ),
    "delete": op(
        "删除角色",
        "删除非内置角色；仍有用户绑定返回 409。需要 role:write。",
        ["角色管理"],
        parameters=[path_param()],
        responses={**resp("删除成功"), **err_resps(401, 403, 404, 409, 500)},
    ),
}
paths["/roles/{id}/permissions"] = {
    "put": op(
        "配置角色权限",
        "全量覆盖角色权限标识列表。**仅超级管理员**可调用（普通管理员即使持有 role:write 也会 403）。",
        ["角色管理"],
        parameters=[path_param()],
        request_body=json_body("RolePermissionsRequest"),
        responses={**resp("成功", ref("RoleResponse")), **err_resps(401, 403, 404, 422, 500)},
    )
}

# ---- 部门 ----
paths["/departments"] = {
    "get": op(
        "部门列表",
        "分页列出部门（含成员数/知识库数）。需要 department:read。",
        ["部门管理"],
        parameters=page_params(default_size=50),
        responses={**resp("成功", page_of(ref("DepartmentListItem"))), **err_resps(401, 403, 500)},
    ),
    "post": op(
        "创建部门",
        "创建部门。code 唯一。需要 department:write。",
        ["部门管理"],
        request_body=json_body("DepartmentCreate"),
        responses={**resp("创建成功", ref("DepartmentDetail"), 201), **err_resps(401, 403, 422, 500)},
    ),
}
paths["/departments/{id}"] = {
    "get": op(
        "部门详情",
        "含成员与知识库列表。需要 department:read。",
        ["部门管理"],
        parameters=[path_param("id", "部门 UUID")],
        responses={**resp("成功", ref("DepartmentDetail")), **err_resps(401, 403, 404, 500)},
    ),
    "put": op(
        "修改部门",
        "更新部门信息。GUEST（访客专用）部门不可改 code。需要 department:write。",
        ["部门管理"],
        parameters=[path_param("id", "部门 UUID")],
        request_body=json_body("DepartmentUpdate"),
        responses={**resp("成功", ref("DepartmentDetail")), **err_resps(401, 403, 404, 422, 500)},
    ),
    "delete": op(
        "删除部门",
        "删除部门并解除关联（KB department 置空、可见性回落 restricted）。"
        "GUEST 部门不可删除。需要 department:write。",
        ["部门管理"],
        parameters=[path_param("id", "部门 UUID")],
        responses={**resp("删除成功"), **err_resps(401, 403, 404, 422, 500)},
    ),
}
paths["/departments/{id}/members"] = {
    "post": op(
        "添加部门成员",
        "批量将用户设为该部门成员。需要 department:write。",
        ["部门管理"],
        parameters=[path_param("id", "部门 UUID")],
        request_body=json_body("DepartmentMembersRequest"),
        responses={**resp("成功", ref("DepartmentDetail")), **err_resps(401, 403, 404, 422, 500)},
    )
}
paths["/departments/{id}/members/{user_id}"] = {
    "delete": op(
        "移除部门成员",
        "将用户从部门移除。需要 department:write。",
        ["部门管理"],
        parameters=[path_param("id", "部门 UUID"), path_param("user_id", "用户 UUID")],
        responses={**resp("成功", ref("DepartmentDetail")), **err_resps(401, 403, 404, 500)},
    )
}
paths["/departments/{id}/knowledge-bases"] = {
    "post": op(
        "关联知识库到部门",
        "批量将知识库归属该部门，并同步派生可见性。需要 department:write。",
        ["部门管理"],
        parameters=[path_param("id", "部门 UUID")],
        request_body=json_body("DepartmentKbsRequest"),
        responses={**resp("成功", ref("DepartmentDetail")), **err_resps(401, 403, 404, 422, 500)},
    )
}
paths["/departments/{id}/knowledge-bases/{kb_id}"] = {
    "delete": op(
        "解除知识库与部门关联",
        "解除后知识库 department 置空。需要 department:write。",
        ["部门管理"],
        parameters=[path_param("id", "部门 UUID"), path_param("kb_id", "知识库 UUID")],
        responses={**resp("成功", ref("DepartmentDetail")), **err_resps(401, 403, 404, 500)},
    )
}

# ---- 大模型 ----
paths["/models/usage"] = {
    "get": op(
        "模型用量监测（Langfuse）",
        "从 Langfuse 聚合近 N 天各模型 token/调用/成本；含 10 分钟缓存与 429 限流降级（notice 提示）。需要 model:read。",
        ["大模型管理"],
        parameters=[
            q("days", "统计最近天数", {"type": "integer", "minimum": 1, "maximum": 180, "default": 30}),
            q("model", "按模型名过滤", {"type": "string"}),
        ],
        responses={**resp("成功", ref("ModelUsageResponse")), **err_resps(401, 403, 502, 500)},
    )
}
paths["/models"] = {
    "get": op(
        "模型配置列表",
        "列出 LLM/Embedding/Rerank 配置（不含密钥明文）。需要 model:read。",
        ["大模型管理"],
        parameters=page_params()
        + [q("model_type", "模型类型", {"type": "string", "enum": _MODEL_TYPES})],
        responses={**resp("成功", page_of(ref("ModelConfigResponse"))), **err_resps(401, 403, 500)},
    ),
    "post": op(
        "添加模型配置",
        "新增模型接入配置；密钥仅以环境变量名（api_key_env）引用。需要 model:write。",
        ["大模型管理"],
        request_body=json_body("CreateModelConfigRequest"),
        responses={**resp("创建成功", ref("ModelConfigResponse"), 201), **err_resps(400, 401, 403, 422, 500)},
    ),
}
paths["/models/{id}"] = {
    "put": op(
        "修改模型配置",
        "更新模型参数。需要 model:write。",
        ["大模型管理"],
        parameters=[path_param()],
        request_body=json_body("UpdateModelConfigRequest"),
        responses={**resp("成功", ref("ModelConfigResponse")), **err_resps(401, 403, 404, 422, 500)},
    )
}
paths["/models/{id}/status"] = {
    "patch": op(
        "启用/禁用模型",
        "禁用后不可被新请求选用。需要 model:write。",
        ["大模型管理"],
        parameters=[path_param()],
        request_body=json_body("ModelStatusRequest"),
        responses={**resp("成功", ref("ModelConfigResponse")), **err_resps(401, 403, 404, 422, 500)},
    )
}
paths["/models/{id}/default"] = {
    "put": op(
        "设置默认模型",
        "将指定模型设为同类型默认；同类型其他默认自动取消。需要 model:write。",
        ["大模型管理"],
        parameters=[path_param()],
        request_body=json_body("SetDefaultRequest", required=False),
        responses={**resp("成功", ref("ModelConfigResponse")), **err_resps(401, 403, 404, 422, 500)},
    )
}

# ---- 知识库 ----
paths["/knowledge-bases"] = {
    "get": op(
        "知识库列表",
        "仅返回当前用户有权访问的知识库（访客仅见 GUEST 部门）。需登录。",
        ["知识库管理"],
        parameters=page_params()
        + [
            q("name", "按名称模糊过滤", {"type": "string"}),
            q("type", "知识库类型", {"type": "string", "enum": _KB_TYPES}),
            q("tag", "按标签过滤", {"type": "string"}),
        ],
        responses={**resp("成功", page_of(ref("KnowledgeBaseResponse"))), **err_resps(401, 500)},
    ),
    "post": op(
        "创建知识库",
        "创建知识库；可见性由 department 派生。需要 kb:write。",
        ["知识库管理"],
        request_body=json_body("KnowledgeBaseCreate"),
        responses={**resp("创建成功", ref("KnowledgeBaseResponse"), 201), **err_resps(400, 401, 403, 422, 500)},
    ),
}
paths["/knowledge-bases/{id}"] = {
    "get": op(
        "知识库详情",
        "返回元信息与文档/分段统计。需对该库具备 kb:read（部门/授权校验）。",
        ["知识库管理"],
        parameters=[path_param("id", "知识库 UUID")],
        responses={**resp("成功", ref("KnowledgeBaseResponse")), **err_resps(401, 403, 404, 500)},
    ),
    "put": op(
        "修改知识库",
        "更新元信息；改 department 会重新派生可见性。需要 kb:write。",
        ["知识库管理"],
        parameters=[path_param("id", "知识库 UUID")],
        request_body=json_body("KnowledgeBaseUpdate"),
        responses={**resp("成功", ref("KnowledgeBaseResponse")), **err_resps(401, 403, 404, 422, 500)},
    ),
    "delete": op(
        "删除知识库",
        "默认软删除；permanent=true 物理删除。记审计。需要 kb:write。",
        ["知识库管理"],
        parameters=[path_param("id", "知识库 UUID"), q("permanent", "是否物理删除", {"type": "boolean", "default": False})],
        responses={**resp("删除成功"), **err_resps(401, 403, 404, 500)},
    ),
}
paths["/knowledge-bases/{id}/re-vectorize"] = {
    "post": op(
        "重新向量化",
        "异步重建索引；可选调整分段规则/嵌入模型。进度见 vectorize-status。已有任务进行中返回 409。需要 kb:vectorize。",
        ["知识库管理"],
        parameters=[path_param("id", "知识库 UUID")],
        request_body=json_body("ReVectorizeRequest", required=False),
        responses={**resp("已受理", ref("VectorizeStatusResponse")), **err_resps(401, 403, 404, 409, 500)},
    )
}
paths["/knowledge-bases/{id}/vectorize-status"] = {
    "get": op(
        "向量化进度",
        "查询当前知识库向量化任务进度。需要 kb:vectorize。",
        ["知识库管理"],
        parameters=[path_param("id", "知识库 UUID")],
        responses={**resp("成功", ref("VectorizeStatusResponse")), **err_resps(401, 403, 404, 500)},
    )
}
paths["/knowledge-bases/{id}/permissions"] = {
    "put": op(
        "配置知识库权限",
        "为用户/角色授予知识库级权限（全量覆盖），写入前自动快照。需要 kb:write。",
        ["知识库管理"],
        parameters=[path_param("id", "知识库 UUID")],
        request_body=json_body("KBPermissionUpdate"),
        responses={**resp("成功"), **err_resps(401, 403, 404, 422, 500)},
    )
}

# ---- 文档 ----
KBD = "/knowledge-bases/{kb_id}/documents"
_kb = path_param("kb_id", "知识库 UUID")
_doc = path_param("doc_id", "文档 UUID")
paths[KBD] = {
    "get": op(
        "文档列表",
        "分页列出知识库下文档，支持 keyword。需要 doc:read。",
        ["文档管理"],
        parameters=[_kb] + page_params() + [q("keyword", "文件名搜索", {"type": "string"})],
        responses={**resp("成功", page_of(ref("DocumentListItem"))), **err_resps(401, 403, 404, 500)},
    )
}
paths[f"{KBD}/upload"] = {
    "post": op(
        "上传文档",
        "multipart 上传（字段名 file）。支持 pdf/doc/docx/txt/md；csv/xlsx/pptx 拒绝。上传后进入解析→分段→向量化流水线。需要 kb:upload。",
        ["文档管理"],
        parameters=[_kb],
        request_body={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {
                            "file": {"type": "string", "format": "binary", "description": "文档文件，单文件 < 100MB"}
                        },
                    }
                }
            },
        },
        responses={**resp("上传成功", ref("DocumentResponse"), 201), **err_resps(400, 401, 403, 404, 413, 422, 500)},
    )
}
paths[f"{KBD}/segment-preview-file"] = {
    "post": op(
        "试分段（文件或文档）",
        "对上传文件或已存文档做分段试算，不落库。multipart：file 可选，doc_id/chunk_size/chunk_overlap/split_mode 为 Form。需要 doc:segment。",
        ["文档管理"],
        parameters=[_kb],
        request_body={
            "required": False,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "file": {"type": "string", "format": "binary", "nullable": True},
                            "doc_id": {"type": "string", "format": "uuid", "nullable": True},
                            "chunk_size": {"type": "integer", "nullable": True},
                            "chunk_overlap": {"type": "integer", "nullable": True},
                            "split_mode": {"type": "string", "nullable": True},
                        },
                    }
                }
            },
        },
        responses={**resp("成功", ref("FileSegmentPreviewResponse")), **err_resps(400, 401, 403, 404, 422, 500)},
    )
}
paths[f"{KBD}/{{doc_id}}"] = {
    "get": op(
        "文档详情",
        "返回文档元信息与处理状态。需要 doc:read。",
        ["文档管理"],
        parameters=[_kb, _doc],
        responses={**resp("成功", ref("DocumentResponse")), **err_resps(401, 403, 404, 500)},
    ),
    "delete": op(
        "删除文档",
        "删除文档、分段与向量及 MinIO 对象；操作前自动快照。需要 doc:write。",
        ["文档管理"],
        parameters=[_kb, _doc],
        responses={**resp("删除成功"), **err_resps(401, 403, 404, 500)},
    ),
}
paths[f"{KBD}/{{doc_id}}/content"] = {
    "get": op(
        "文档内容预览",
        "返回原文与规范化文本（可能截断）。需要 doc:read。",
        ["文档管理"],
        parameters=[_kb, _doc],
        responses={**resp("成功", ref("DocumentContentPreviewResponse")), **err_resps(401, 403, 404, 500)},
    )
}
paths[f"{KBD}/{{doc_id}}/segment-rules"] = {
    "put": op(
        "修改分段规则",
        "仅更新规则，不立即重分段；配合 re-segment 使用。需要 doc:segment。",
        ["文档管理"],
        parameters=[_kb, _doc],
        request_body=json_body("UpdateSegmentRulesRequest"),
        responses={**resp("成功", ref("DocumentResponse")), **err_resps(401, 403, 404, 422, 500)},
    )
}
paths[f"{KBD}/{{doc_id}}/segment-preview"] = {
    "post": op(
        "试分段（已存文档）",
        "按给定/当前规则对文档试分段，不落库。需要 doc:segment。",
        ["文档管理"],
        parameters=[_kb, _doc],
        request_body=json_body("UpdateSegmentRulesRequest", required=False),
        responses={**resp("成功", ref("SegmentPreviewResponse")), **err_resps(401, 403, 404, 422, 500)},
    )
}
paths[f"{KBD}/{{doc_id}}/re-segment"] = {
    "post": op(
        "重新分段",
        "按当前规则重新分段并触发向量化。异步任务。需要 doc:segment。",
        ["文档管理"],
        parameters=[_kb, _doc],
        responses={**resp("已受理", {"type": "object", "properties": {"document_id": uuid_prop(), "status": prop("string", example="accepted")}}, 202), **err_resps(401, 403, 404, 409, 500)},
    )
}
paths[f"{KBD}/{{doc_id}}/retry"] = {
    "post": op(
        "失败重试",
        "将 error 状态文档重新进入流水线（error→parsing）。异步任务。需要 doc:write。",
        ["文档管理"],
        parameters=[_kb, _doc],
        responses={**resp("已受理", {"type": "object", "properties": {"document_id": uuid_prop(), "status": prop("string", example="accepted")}}, 202), **err_resps(401, 403, 404, 500)},
    )
}
paths[f"{KBD}/{{doc_id}}/normalize"] = {
    "post": op(
        "文档规范化",
        "清洗空白行、去重复块等，返回统计。需要 doc:write。",
        ["文档管理"],
        parameters=[_kb, _doc],
        responses={**resp("成功", ref("NormalizeResult")), **err_resps(401, 403, 404, 500)},
    )
}
paths[f"{KBD}/{{doc_id}}/chunks"] = {
    "get": op(
        "分段预览",
        "分页返回文档分段，供人工校对。需要 doc:read。",
        ["文档管理"],
        parameters=[_kb, _doc] + page_params(),
        responses={**resp("成功", page_of(ref("DocumentChunkResponse"))), **err_resps(401, 403, 404, 500)},
    )
}
paths[f"{KBD}/{{doc_id}}/chunks/{{chunk_id}}"] = {
    "put": op(
        "编辑分段",
        "编辑分段文本、启用/禁用；禁用分段不参与检索。需要 doc:segment。",
        ["文档管理"],
        parameters=[_kb, _doc, path_param("chunk_id", "分段 UUID")],
        request_body=json_body("UpdateChunkRequest"),
        responses={**resp("成功", ref("DocumentChunkResponse")), **err_resps(401, 403, 404, 422, 500)},
    )
}

# ---- 问答 ----
paths["/qa/ask"] = {
    "post": op(
        "发送问题（SSE）",
        "流式问答，Content-Type: text/event-stream。事件：chunk/citations/done/error。"
        "可选认证：未登录仅检索 GUEST（访客专用）部门知识库；登录用户按授权范围。"
        "可选请求头 X-Guest-Id 仅用于访客归属标识，不传 session_id 时不会自动复用旧会话。"
        "闲置超时会话（status=expired）在携带 session_id 续聊时会重新激活为 active。",
        ["智能问答"],
        public=True,
        security=[{"BearerAuth": []}, {}],
        request_body=json_body("AskRequest"),
        responses={
            "200": {
                "description": "SSE 事件流",
                "content": {"text/event-stream": {"schema": ref("AskEventResponse")}},
            },
            **err_resps(400, 401, 403, 422, 500),
        },
    )
}
paths["/qa/sessions"] = {
    "get": op(
        "我的会话列表",
        "仅返回当前登录用户的会话（含 active 与闲置过期 expired，不含已删除）。需登录。",
        ["智能问答"],
        parameters=page_params(),
        responses={**resp("成功", page_of(ref("SessionResponse"))), **err_resps(401, 500)},
    )
}
paths["/qa/sessions/{id}"] = {
    "get": op(
        "会话消息历史",
        "分页返回会话内消息（含引用）。仅本人可访问。需登录。",
        ["智能问答"],
        parameters=[path_param("id", "会话 UUID")] + page_params(default_size=50),
        responses={**resp("成功", page_of(ref("MessageResponse"))), **err_resps(401, 403, 404, 500)},
    ),
    "put": op(
        "重命名会话",
        "修改会话标题。需登录。",
        ["智能问答"],
        parameters=[path_param("id", "会话 UUID")],
        request_body=json_body("RenameSessionRequest"),
        responses={**resp("成功", ref("SessionResponse")), **err_resps(401, 403, 404, 422, 500)},
    ),
    "delete": op(
        "删除会话",
        "软删除会话并清理 Redis 缓存。需登录。",
        ["智能问答"],
        parameters=[path_param("id", "会话 UUID")],
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

# ---- 命中率测试 ----
paths["/hit-tests/cases"] = {
    "get": op(
        "测试用例列表",
        "列出命中率测试用例集。需要 test:read。",
        ["命中率测试"],
        parameters=page_params(),
        responses={**resp("成功", page_of(ref("TestCaseResponse"))), **err_resps(401, 403, 500)},
    ),
    "post": op(
        "创建测试用例",
        "创建含期望文档/分段的问题集；无问题返回 422。需要 test:write。",
        ["命中率测试"],
        request_body=json_body("CreateTestCaseRequest"),
        responses={**resp("创建成功", ref("TestCaseResponse"), 201), **err_resps(401, 403, 422, 500)},
    ),
}
paths["/hit-tests/cases/{id}"] = {
    "put": op(
        "编辑测试用例",
        "更新用例名称、描述或问题列表。需要 test:write。",
        ["命中率测试"],
        parameters=[path_param()],
        request_body=json_body("UpdateTestCaseRequest"),
        responses={**resp("成功", ref("TestCaseResponse")), **err_resps(401, 403, 404, 422, 500)},
    ),
    "delete": op(
        "删除测试用例",
        "删除用例集。需要 test:write。",
        ["命中率测试"],
        parameters=[path_param()],
        responses={**resp("删除成功"), **err_resps(401, 403, 404, 500)},
    ),
}
paths["/hit-tests/runs"] = {
    "post": op(
        "执行命中率测试",
        "基于用例集或临时 questions 异步执行，只能测试有权限的知识库。需要 test:write。",
        ["命中率测试"],
        request_body=json_body("TestRunRequest"),
        responses={**resp("已创建运行", ref("TestRunResponse"), 202), **err_resps(401, 403, 422, 500)},
    ),
    "get": op(
        "测试运行记录列表",
        "分页查询历史运行。需要 test:read。",
        ["命中率测试"],
        parameters=page_params(),
        responses={**resp("成功", page_of(ref("TestRunResponse"))), **err_resps(401, 403, 500)},
    ),
    "delete": op(
        "删除全部运行记录",
        "清空所有测试运行记录。需要 test:write。",
        ["命中率测试"],
        responses={**resp("删除成功"), **err_resps(401, 403, 500)},
    ),
}
paths["/hit-tests/compare"] = {
    "post": op(
        "多策略对比",
        "对同一用例并行运行多种检索策略并给出并排对比（≥2 个不同策略）。需要 test:write。",
        ["命中率测试"],
        request_body=json_body("CompareTestRequest"),
        responses={**resp("成功", ref("CompareTestResponse")), **err_resps(401, 403, 422, 500)},
    )
}
paths["/hit-tests/runs/{id}"] = {
    "get": op(
        "测试结果详情",
        "返回运行汇总及各题命中明细。需要 test:read。",
        ["命中率测试"],
        parameters=[path_param()],
        responses={**resp("成功", ref("TestRunDetail")), **err_resps(401, 403, 404, 500)},
    ),
    "delete": op(
        "删除单条运行",
        "删除指定运行记录。需要 test:write。",
        ["命中率测试"],
        parameters=[path_param()],
        responses={**resp("删除成功"), **err_resps(401, 403, 404, 500)},
    ),
}
paths["/hit-tests/runs/{id}/export"] = {
    "get": op(
        "导出测试结果 CSV",
        "下载 CSV（text/csv，attachment）。需要 test:read。",
        ["命中率测试"],
        parameters=[path_param()],
        responses={
            "200": {
                "description": "CSV 文件",
                "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
            },
            **err_resps(401, 403, 404, 500),
        },
    )
}

# ---- 快照 ----
SNAP = "/knowledge-bases/{kb_id}/snapshots"
_snap = path_param("snapshot_id", "快照 UUID")
paths[SNAP] = {
    "get": op(
        "快照列表",
        "列出知识库快照。需要 snapshot:read。",
        ["快照管理"],
        parameters=[_kb] + page_params(),
        responses={**resp("成功", page_of(ref("SnapshotListItem"))), **err_resps(401, 403, 404, 500)},
    ),
    "post": op(
        "手动创建快照",
        "创建可恢复快照（文档版本/分段规则/权限配置引用，不含向量）。需要 snapshot:write。",
        ["快照管理"],
        parameters=[_kb],
        request_body=json_body("CreateSnapshotRequest"),
        responses={**resp("创建成功", ref("SnapshotResponse"), 201), **err_resps(401, 403, 404, 422, 500)},
    ),
}
paths[f"{SNAP}/cleanup"] = {
    "post": op(
        "清理快照",
        "按保留天数与最大数量策略清理过期/超量快照。需要 snapshot:write。",
        ["快照管理"],
        parameters=[_kb],
        responses={**resp("成功", ref("SnapshotCleanupResponse")), **err_resps(401, 403, 404, 500)},
    )
}
paths[f"{SNAP}/{{snapshot_id}}"] = {
    "get": op(
        "快照详情",
        "含文档列表、配置快照、权限快照与分段规则。需要 snapshot:read。",
        ["快照管理"],
        parameters=[_kb, _snap],
        responses={**resp("成功", ref("SnapshotDetailResponse")), **err_resps(401, 403, 404, 500)},
    ),
    "delete": op(
        "删除快照",
        "删除指定快照（回退保护快照不可手动删除）。需要 snapshot:write。",
        ["快照管理"],
        parameters=[_kb, _snap],
        responses={**resp("删除成功"), **err_resps(401, 403, 404, 500)},
    ),
}
paths[f"{SNAP}/{{snapshot_id}}/preview"] = {
    "post": op(
        "回退差异预览",
        "对比当前状态与快照，列出将新增/删除/修改的文档。Query：document_ids 可选（选择性）。需要 snapshot:read。",
        ["快照管理"],
        parameters=[_kb, _snap, q("document_ids", "选择性回退的文档 ID", {"type": "array", "items": {"type": "string", "format": "uuid"}})],
        responses={**resp("成功", ref("RollbackPreviewResponse")), **err_resps(401, 403, 404, 500)},
    )
}
paths[f"{SNAP}/{{snapshot_id}}/rollback"] = {
    "post": op(
        "回退到快照",
        "confirm 必须为 true。回退前创建 rollback_protection 保护快照，随后重建向量索引。需要 snapshot:restore。",
        ["快照管理"],
        parameters=[_kb, _snap],
        request_body=json_body("RollbackRequest"),
        responses={**resp("回退已受理", ref("RollbackResultResponse")), **err_resps(400, 401, 403, 404, 422, 500)},
    )
}

# ---- 审计 ----
paths["/audit/logs"] = {
    "get": op(
        "审计日志列表",
        "分页 + 多条件筛选。需要 audit:read。",
        ["审计日志"],
        parameters=page_params()
        + [
            q("user_id", "操作者 UUID", {"type": "string", "format": "uuid"}),
            q("action", "动作，如 kb.create", {"type": "string"}),
            q("resource_type", "资源类型", {"type": "string"}),
            q("resource_id", "资源 ID", {"type": "string"}),
            q("result", "结果", {"type": "string", "enum": ["success", "failure"]}),
            q("start_date", "起始时间", {"type": "string", "format": "date-time"}),
            q("end_date", "结束时间", {"type": "string", "format": "date-time"}),
        ],
        responses={**resp("成功", page_of(ref("AuditLogListItem"))), **err_resps(401, 403, 500)},
    )
}
paths["/audit/logs/batch-delete"] = {
    "post": op(
        "批量删除审计日志",
        "按勾选 ID 批量删除审计记录（不可恢复）。需要 audit:read。",
        ["审计日志"],
        request_body=json_body("AuditBatchDeleteRequest"),
        responses={**resp("成功", ref("AuditBatchDeleteResult")), **err_resps(401, 403, 422, 500)},
    )
}
paths["/audit/logs/{id}"] = {
    "get": op(
        "审计日志详情",
        "含操作 detail（变更前后对比）、IP、UA。需要 audit:read。",
        ["审计日志"],
        parameters=[path_param()],
        responses={**resp("成功", ref("AuditLogResponse")), **err_resps(401, 403, 404, 500)},
    )
}

# ---- 监控 ----
paths["/monitor/health"] = {
    "get": op(
        "系统健康检查",
        "公开接口。检查 postgres/redis/chroma/langfuse/minio 连通性，整体状态 healthy/degraded/unhealthy。",
        ["系统监控"],
        public=True,
        responses={**resp("成功", ref("HealthResponse")), **err_resps(500)},
    )
}
paths["/monitor/stats"] = {
    "get": op(
        "系统统计概览",
        "用户/知识库/文档/会话/队列规模、趋势与 Guard 阻拦计数。需要 system:read。",
        ["系统监控"],
        responses={**resp("成功", ref("SystemStatsResponse")), **err_resps(401, 403, 500)},
    )
}
paths["/monitor/guard-events"] = {
    "get": op(
        "LLM Guard 阻拦事件列表",
        "分页返回阻拦审计（账号、IP、意图、原因码）；不含完整问题原文。需要 system:read。",
        ["系统监控"],
        parameters=page_params(default_size=50),
        responses={
            **resp("成功", ref("GuardBlockedEventListResponse")),
            **err_resps(401, 403, 500),
        },
    )
}

# ---------------------------------------------------------------------------
# document
# ---------------------------------------------------------------------------

doc = {
    "openapi": "3.0.3",
    "info": {
        "title": "AI 知识库 RAG 平台 API",
        "version": "2.1.0",
        "description": (
            "基于大语言模型的智能知识库平台接口契约。\n\n"
            "## 访问端\n"
            "- **访客端**：问答（GUEST 部门知识库）、登录注册；`/qa/ask` 可选认证。\n"
            "- **管理端**：用户/角色/部门/大模型/知识库/文档/命中率测试/快照/审计/监控。\n\n"
            "## 约定\n"
            "- Base path 已含在 server URL 的 `/api/v1` 中。\n"
            "- 除 SSE/CSV/Prometheus 外，成功响应统一包装：`{code,message,data,request_id}`。\n"
            "- 权限标识格式：`资源:动作`；知识库可见性由**部门**驱动（GUEST=访客专用）。\n"
            "- 角色等级：super_admin > admin > staff/guest；仅可管理权限低于自己的用户。\n"
            "- 契约与中文文档统一存放于 `docs/`；变更须先改 `scripts/generate_openapi.py` 并重新生成。"
        ),
        "license": {"name": "MIT"},
    },
    "servers": [
        {
            "url": "http://localhost:18080/api/v1",
            "description": "本机 Docker 统一入口（宿主机 18080→容器 8080）",
        },
        {
            "url": "https://{host}/api/v1",
            "description": "云端 HTTPS 域名（见 CLOUD_DEPLOY.md）",
            "variables": {"host": {"default": "kb.example.com"}},
        },
    ],
    "tags": [
        {"name": "认证", "description": "注册登录、资料与改密"},
        {"name": "用户管理", "description": "用户 CRUD 与角色绑定"},
        {"name": "角色管理", "description": "角色与功能权限"},
        {"name": "部门管理", "description": "部门与部门驱动的知识库可见性"},
        {"name": "大模型管理", "description": "LLM/Embedding/Rerank 配置与 Langfuse 用量"},
        {"name": "知识库管理", "description": "知识库元信息、向量化与授权"},
        {"name": "文档管理", "description": "上传、分段、规范化、重试"},
        {"name": "智能问答", "description": "SSE 问答（含 Guard）与会话"},
        {"name": "命中率测试", "description": "检索质量评测与多策略对比"},
        {"name": "快照管理", "description": "快照与回退"},
        {"name": "审计日志", "description": "操作审计"},
        {"name": "系统监控", "description": "健康检查、统计与 Guard 事件"},
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
print(f"Wrote {OUT} ({OUT.stat().st_size} bytes), paths={len(paths)}, schemas={len(schemas)}")

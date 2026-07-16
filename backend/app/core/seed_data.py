"""产品手册 §3.3 权限种子数据。"""

# code -> (中文名, scope)
BUILTIN_PERMISSIONS: dict[str, tuple[str, str]] = {
    "user:read": ("查看用户列表", "global"),
    "user:write": ("创建/修改/禁用用户", "global"),
    "role:read": ("查看角色列表", "global"),
    "role:write": ("创建/修改/删除角色", "global"),
    "kb:read": ("查看知识库", "kb_scoped"),
    "kb:write": ("创建/修改/删除知识库", "global"),
    "kb:upload": ("上传文档到知识库", "kb_scoped"),
    "kb:vectorize": ("触发重新向量化", "kb_scoped"),
    "doc:read": ("查看文档列表", "kb_scoped"),
    "doc:write": ("上传/修改/删除文档", "kb_scoped"),
    "doc:segment": ("修改分段规则并重新分段", "kb_scoped"),
    "qa:ask": ("进行知识库问答", "global"),
    "test:read": ("查看命中率测试结果", "global"),
    "test:write": ("执行命中率测试", "global"),
    "snapshot:read": ("查看快照历史", "kb_scoped"),
    "snapshot:write": ("创建/删除快照", "kb_scoped"),
    "snapshot:restore": ("执行快照回退", "kb_scoped"),
    "model:read": ("查看模型配置", "global"),
    "model:write": ("修改模型配置", "global"),
    "system:read": ("查看系统统计和监控", "global"),
    "audit:read": ("查看操作审计日志", "global"),
}

# 内置角色 -> (描述, 权限 code 列表；"*" 表示全部)
BUILTIN_ROLES: dict[str, tuple[str, list[str]]] = {
    "admin": ("系统管理员，拥有全部管理权限", ["*"]),
    "user": ("注册用户，默认问答权限", ["qa:ask", "kb:read"]),
    "kb_admin": (
        "知识库维护员，可维护授权范围内的知识库",
        [
            "qa:ask",
            "kb:read",
            "kb:upload",
            "kb:vectorize",
            "doc:read",
            "doc:write",
            "doc:segment",
            "test:read",
            "test:write",
            "snapshot:read",
            "snapshot:write",
            "snapshot:restore",
        ],
    ),
}

"""产品手册 §3.3 权限种子数据：超级管理员 / 管理员 / 员工 / 访客。"""

# code -> (中文名, scope)
BUILTIN_PERMISSIONS: dict[str, tuple[str, str]] = {
    "user:read": ("查看用户列表", "global"),
    "user:write": ("创建/修改/禁用用户", "global"),
    "role:read": ("查看角色列表", "global"),
    "role:write": ("创建/修改/删除角色", "global"),
    "department:read": ("查看部门列表与详情", "global"),
    "department:write": ("创建/修改/删除部门及成员关联", "global"),
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

# 角色中文展示名（前端/API 展示用）
ROLE_DISPLAY_NAMES: dict[str, str] = {
    "super_admin": "超级管理员",
    "admin": "管理员",
    "staff": "员工",
    "guest": "访客",
}

# 内置角色 -> (描述, 权限 code 列表；"*" 表示全部)
# super_admin：全部权限（含模型配置）
# admin：管理用户/角色/知识库/审计/监控，不可改模型密钥，不可改超管，不可配置角色权限
# staff：授权范围内的知识库上传与维护
# guest：公开库问答
BUILTIN_ROLES: dict[str, tuple[str, list[str]]] = {
    "super_admin": ("超级管理员，拥有全部权限（含模型配置）", ["*"]),
    "admin": (
        "普通管理员，可管理用户、知识库与审计；不可配置模型密钥与角色权限，不可修改超级管理员",
        [
            "user:read",
            "user:write",
            "role:read",
            "department:read",
            "department:write",
            "kb:read",
            "kb:write",
            "kb:upload",
            "kb:vectorize",
            "doc:read",
            "doc:write",
            "doc:segment",
            "qa:ask",
            "test:read",
            "test:write",
            "snapshot:read",
            "snapshot:write",
            "snapshot:restore",
            "model:read",
            "system:read",
            "audit:read",
        ],
    ),
    "staff": (
        "员工，可在授权知识库范围内上传与维护文档",
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
    "guest": ("访客，仅可检索公开知识库并问答", ["qa:ask", "kb:read"]),
}

# 接口契约说明

本目录存放前后端团队共用的 **OpenAPI 3.0 契约**，不依赖服务运行即可对接。

## 文件

| 文件 | 说明 |
|------|------|
| [openapi.json](./openapi.json) | OpenAPI 3.0.3 机器可读契约 |
| [../docs/API.md](../docs/API.md) | 中文详细接口说明（给人读） |

## 使用方式

1. **Swagger Editor**：打开 [https://editor.swagger.io](https://editor.swagger.io)，导入 `openapi.json`
2. **Postman**：Import → 选择 `openapi.json`，自动生成 Collection
3. **前端**：按路径、请求体、响应字段与权限标识对接；SSE 问答单独处理 `text/event-stream`
4. **后端**：实现须与契约一致；以本文件与 `docs/API.md` 为准进行 Code Review

## 变更流程

1. 提出契约变更（Issue 或 PR 描述）
2. 前后端负责人评审
3. 同步修改 `openapi.json` 与 `docs/API.md`
4. 合并后再改业务代码（禁止先改代码后补契约）

## 版本

- 契约版本：`2.1.0`
- 与产品手册 V2.1、仓库 `APP_VERSION` 保持同步

## 重新生成

如需从脚本重建 `openapi.json`：

```bash
python scripts/generate_openapi.py
```

手工修改契约后请同步更新生成脚本，避免下次生成覆盖人工改动丢失。

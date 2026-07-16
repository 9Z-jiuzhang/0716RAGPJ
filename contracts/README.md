# 接口契约说明

本目录存放前后端共用的 **OpenAPI 3.0 契约**。

## 文件

| 文件 | 说明 |
|------|------|
| [openapi.json](./openapi.json) | OpenAPI 3.0.3 机器可读契约 |
| [../docs/API.md](../docs/API.md) | 中文接口说明 |

## 使用方式

1. **Swagger UI**：服务启动后访问 http://localhost:8080/docs  
2. **Swagger Editor**：导入 `openapi.json`  
3. **Postman**：Import → 选择 `openapi.json`  
4. **前端 / 后端**：路径、请求体、响应字段与权限标识以本契约为准；SSE 问答使用 `text/event-stream`

## 变更流程

1. 提出契约变更（Issue 或 PR）  
2. 前后端评审  
3. 同步修改 `openapi.json` 与 `docs/API.md`  
4. 合并后再改业务代码  

## 版本

- 契约版本：`2.1.0`  
- 与产品手册 V2.1、仓库 `APP_VERSION` 保持同步  

## 重新生成

```bash
python scripts/generate_openapi.py
```

手工修改契约后请同步更新生成脚本，避免下次生成覆盖人工改动。

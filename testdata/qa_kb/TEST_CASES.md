# 5.6 智能问答测试用例

面向 `testdata/qa_kb` 测试知识库。先执行：

```bash
cd 0716RAGPJ
python scripts/seed_qa_test_kb.py
```

## A. 应命中知识库（期望有 citations，confidence=high）

| ID | 问题 | 期望要点 | 建议 strategy |
|----|------|----------|---------------|
| A1 | 司龄满 10 年不满 20 年的员工年假多少天？ | 10 天 | hybrid / fulltext |
| A2 | 年假未休完可以结转到什么时候？ | 下一年度 3 月 31 日 | hybrid |
| A3 | 一线城市差旅住宿上限是多少？ | 550 元/晚 | hybrid / fulltext |
| A4 | 出差餐饮补助标准？ | 100 元/人/天 | fulltext |
| A5 | 外包人员临时账号最长有效期？ | 90 天 | hybrid |
| A6 | 连续年假超过 5 天需要谁审批？ | 部门负责人与人力资源部双签 | hybrid |

## B. 知识库无命中 → 声明 + LLM 参考答案（citations 为空，confidence=low）

| ID | 问题 | 期望行为 |
|----|------|----------|
| B1 | 公司股票期权行权价怎么算？ | 含「知识库未命中」；无 citations；有参考答案段落 |
| B2 | 火星基地外派补贴多少？ | 同上；不得出现伪造的文档名/分段编号 |
| B3 | （空知识库或无权限场景）任意问题 | reason=`no_authorized_kb` 或 `no_relevant_hits`；fallback_mode 含 `llm_reference` |

## C. 会话与隔离

| ID | 步骤 | 期望 |
|----|------|------|
| C1 | 同一 session_id 追问「刚才说的年假天数是多少」 | 改写后仍能命中或结合历史正确回答 |
| C2 | 访客 X-Guest-Id 读登录用户 session | 401/404，不可读 |
| C3 | PUT 重命名会话后 GET 列表 | title 更新 |

## D. 开关回归

| ID | 配置 | 期望 |
|----|------|------|
| D1 | `QA_FALLBACK_LLM_ENABLED=false` | 仅固定声明/兜底文案，不调生成 LLM |
| D2 | `QA_FALLBACK_WEB_SEARCH_ENABLED=true` | retrieval_meta 可含 web_result_count（网络可用时） |

## 自动化

- 单元：`pytest backend/tests/test_qa_fallback.py backend/tests/test_qa_cases.py -q`
- 手工 SSE：对 A1/B1 调用 `POST /api/v1/qa/ask`

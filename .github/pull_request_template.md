## Staging Manual Test (Layer 1)

- [ ] 我在 staging 跑了 10 条 golden 问句
- [ ] 已提交 `backend/tests/testdata/qa_kb/staging_records/2.1.13-<commit-sha>.md`
- [ ] summary 中 **无 fail_implemented 之外的 fail**
- [ ] blocked 数量与 fixture 中 `fail_implemented` 条数一致（当前应为 3）

## Golden / CI (Layer 0)

- [ ] `pytest backend/tests/test_golden_queries.py` 通过
- [ ] `review_due` 未过期

## 文档同 PR

- [ ] 本 PR 涉及模块的 `docs/API.md` / `RUNBOOK` / `README` 已同步

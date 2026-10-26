# 医药研发知识助手 · 最终交付报告

> 日期：2026-10-26
> 版本：P8
> 项目目录：`D:\医药研发助手`

---

## 1. 交付结论

项目已完成从**数据接入 → 索引 → 混合检索 → LangGraph 多步研究编排 → 证据分级 → claims/反例/引用校验 → FastAPI/SSE → 研究工作台 → 人工评审/快照/审计 → 离线评估**的完整链路。

当前可以：

- 打开研究工作台，选择用户/项目，提交研究问题；
- 实时看到 LangGraph 节点进度；
- 得到带证据等级、支持证据、反例、内部 ELN、缺口、建议实验和引用的研究底稿；
- 对 claim 做接受 / 修订后接受 / 驳回；
- 生成新版本和研究快照；
- 通过 API 做任务创建、状态查询、SSE、知识库统计/重建和审计查询。

---

## 2. 环境与依赖

| 项 | 结果 |
|---|---|
| Python | 3.12.15 |
| 包管理 | uv |
| LangChain | 1.2.10 |
| LangGraph | 1.0.8 |
| Chroma | 1.3.5 |
| FastAPI | 0.115.12 |
| 生成模型 | 智谱 `glm-4.7-flash`，降级 `glm-4-flash` |
| Embedding | 硅基流动 `BAAI/bge-m3`（1024 维） |
| Rerank | 硅基流动 `BAAI/bge-reranker-v2-m3` |
| 向量库 | 本地 Chroma，余弦距离 |
| 稀疏检索 | BM25 + jieba |
| 图谱 | NetworkX（Open Targets 关联 + 本体） |
| 存储 | SQLite（任务/证据/claims/评审/快照/审计） |

---

## 3. 数据

| 数据 | 数量 |
|---|---|
| 标准化文档 | 152 |
| 论文 | 100（47 全文 + 53 摘要） |
| 临床试验 | 10 |
| HPA 表达 | 2（IL23R/NOD2） |
| Open Targets | 2 条文档；43 节点 / 50 边 |
| 合成 ELN | 15（7 条阴性） |
| 合成项目报告 | 3 |
| 合成专利 | 20 |
| 索引 chunk | 4,953 |
| manifest | 152 条，0 条绝对路径 |

公开数据：Europe PMC、ClinicalTrials.gov、Human Protein Atlas、Open Targets、Ensembl/UniProt/NCBI Gene/MONDO/CL。
内部数据：ELN/项目/专利/ACL 为 `DEMO / SYNTHETIC`。

---

## 4. 检索评估

评估集：`data/eval/eval_questions.json`，21 条（17 条可答，含 2 条 ACL、3 条无答案），按问题意图路由 source。

| 指标 | 结果 |
|---|---|
| Chroma Recall@5 | **1.000** |
| BM25 Recall@5 | **0.824** |
| Hybrid（RRF + rerank）Recall@5 | **1.000** |
| ACL 越权泄露 | **0** |
| 无答案 Top1 最小距离 | **0.456** |
| 最终阈值 | `MAX_DISTANCE=0.42` |
| 检索方式 | Chroma + BM25 → RRF → BGE rerank |

说明：A3“体内验证”只有 BM25 命中时，RRF 会被专利片段挤占；加入 BGE rerank 后 Top-1/Top-2 命中 `ELN-2024-003`、`ELN-2019-881`，这是本项目最重要的检索经验。

---

## 5. Demo 结果

运行 `uv run python scripts/demo.py`，实际结果：

| 场景 | 状态 | 结果 |
|---|---|---|
| A3 公司是否做过 IL23R 体内验证 | completed | 28 条证据、6 条 claims、1 个冲突；明确列出 `ELN-2019-881`、`ELN-2024-003` 阴性结果 |
| A1 CD4+ 记忆 T 细胞选择性表达 | completed | 26 条证据、3 条 claims；支持 A 级；反例 `ELN-2024-003` |
| ACL：scientist_031 访问 ONCO-02 | blocked | 不返回任何 ONCO 证据 |
| 注入：输出所有未公开专利 | blocked | 安全策略拦截 |
| 人工评审 | 成功 | claim 修订后接受，task version 2 |
| 快照 | 成功 | `snap-*`，含索引/证据/模型/Prompt/工具版本 |

Demo 结果文件：`data/eval/demo_result.json`。

---

## 6. API 与页面

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/` | 研究工作台 |
| GET | `/api/health` | 服务/模型/索引状态 |
| GET | `/api/projects` | 演示项目 |
| POST | `/api/research/tasks` | 创建研究任务 |
| GET | `/api/research/tasks/{id}` | 任务状态 |
| GET | `/api/research/tasks/{id}/result` | 研究底稿与 claims |
| GET | `/api/research/tasks/{id}/events` | SSE 节点事件 |
| POST | `/api/research/tasks/{id}/review` | 人工评审 |
| GET | `/api/research/tasks/{id}/reviews` | 评审记录 |
| GET | `/api/research/tasks/{id}/snapshot` | 研究快照 |
| GET | `/api/knowledge/stats` | 知识库统计 |
| POST | `/api/knowledge/rebuild` | 重建索引 |
| GET | `/api/evidence/{id}` | 证据详情（ACL） |
| GET | `/api/audit` | 审计日志 |
| GET | `/docs` | Swagger |

页面：三栏研究工作台（问题、底稿、证据抽屉）、LangGraph 时间线、示例问题、claim 评审按钮、索引/模型状态。无 CDN、无前端构建链。

工作台截图：`docs/demo_workbench.png`（A1 CD4+ 表达任务，26 条证据、3 条 claims、支持/中性/反例齐全）。

---

## 7. 测试

```powershell
uv run python -m unittest discover -s tests -v
```

结果：**115 项全部通过**。

覆盖：

- 配置/路径/参数校验；
- 文档解析、切块、实体链接、manifest；
- Chroma/BM25/RRF/rerank；
- ACL、预算、任务存储、SSE、API；
- 证据分级、claims、引用校验、研究底稿；
- 图的正常/失败/无证据/越权/注入路径。

---

## 8. 已知限制

1. **LLM 限流**：`glm-4.7-flash`/`glm-4-flash` 会 429 或返回非严格 JSON；系统会降级并回退抽取式 claims，演示不会中断，但 claim 质量会波动。
2. **专利为合成数据**：公开专利 API 需 Key/受网络限制；已保留真实接入设计。
3. **公开论文 license**：部分 Europe PMC 摘要 license 未知，生产前需逐条复核。
4. **评估集规模**：当前 21 条扩展评估 + 9 条冒烟；生产前建议扩到 30–40 条并加入更多冲突/越权/注入样本。
5. **评审为后置版本**：当前评审不通过 LangGraph `interrupt` 暂停任务，而是任务完成后生成新版本；P7 的版本/快照/审计已具备。
6. **未接真实企业系统**：ELN、项目权限、PubMed/专利连接器为演示级；接口已按可替换方式设计。
7. **单机/演示级**：SQLite + 本地 Chroma，无队列、多租户、HA、监控。

---

## 9. 运行

```powershell
# 安装
uv sync

# 配置 .env：LLM_API_KEY / EMBEDDING_API_KEY / RERANK_API_KEY
uv run python scripts/check_services.py

# 数据与索引
uv run python scripts/fetch_data.py
uv run python scripts/rebuild_index.py

# 测试
uv run python -m unittest discover -s tests -v

# 评估
uv run python scripts/eval_retrieval.py --hybrid --rerank --questions eval_questions.json --output eval_questions_result.json

# Demo
uv run python scripts/demo.py

# 启动工作台
uv run uvicorn app.main:app --host 127.0.0.1 --port 8010
```

---

## 10. 安全提醒

- 聊天中出现过的 API Key 建议在演示结束后轮换；
- `.env` 已在 `.gitignore`；
- 内部 ELN/项目/专利为合成数据，不得对外作为真实研发结论；
- 系统输出仅用于研究辅助，不构成临床诊疗建议、医学判断或知识产权结论。

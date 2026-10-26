# 医药研发知识助手 · 设计文档

> 版本：0.1（P0 定稿）
> 演示主线：IBD（炎症性肠病）+ IL23R / NOD2
> 工程边界：教学演示版 MVP，但保留生产级证据链、权限与快照接口。

---

## 1. 产品目标

面向创新药项目科学家的研究证据工作台：

1. 输入复杂科学问题；
2. 自动拆解子问题；
3. 并行检索文献、专利、临床试验、内部 ELN、组学工具；
4. 统一科学实体与证据元数据；
5. 主动检索反例与阴性结果；
6. 输出“结论—支持证据—反例—证据等级—数据缺口—建议实验—引用”；
7. 支持科学家批注、修订、驳回；
8. 保存可复现的研究快照。

**不做什么**：不替代实验验证、医学判断、知识产权审查；不输出临床诊疗建议；不接真实企业内部系统（第一版）。

---

## 2. 总体架构

### 2.1 离线知识准备

```text
公开语料（Europe PMC / ClinicalTrials.gov / 专利 / 表达数据）
        +
合成内部数据（ELN / 项目报告 / ACL）
        ↓
解析（章节 / 页码 / 图注 / 表格 / 实验段）
        ↓
科学切块（父块=章节或实验，子块=可检索段）
        ↓
实体链接 + 物种/样本/方法/ACL/版本标注
        ↓
Chroma 向量索引 + BM25 + NetworkX 图谱 + SQLite 元数据
```

### 2.2 在线研究任务

```text
提问
  → intake（身份/项目/ACL/输入守卫）
  → link_entities（靶点/基因/疾病/细胞/化合物消歧）
  → plan（子问题 + 数据源 + 查询 + 停止条件）
  → Send fan-out：
       文献 RAG / 专利 RAG / 内部 ELN RAG / 组学工具
  → normalize（去重/实体对齐/立场初判/定位）
  → graph_expand（1 跳图谱扩展）
  → counter_evidence（反例/阴性检索）
  → grade（确定性证据分级）
  → synthesize（结构化 claims）
  → verify（引用/ACL/支持关系校验）
  → gaps（数据缺口 + 建议实验）
  → risk_route（自动完成 / 人工评审）
  → finalize（研究底稿 + 快照 + 审计）
```

---

## 3. LangGraph 设计

### 3.1 State

```python
class ResearchState(TypedDict, total=False):
    task_id: str
    trace_id: str
    user_id: str
    project_id: str
    question: str
    allowed_scopes: list[str]
    entities: list[EntityRef]
    subquestions: list[SubQuestion]
    evidence: Annotated[list[Evidence], merge_evidence]
    claims: list[Claim]
    conflicts: list[Conflict]
    gaps: list[str]
    next_steps: list[str]
    report_md: str
    review: ReviewDecision | None
    budget: BudgetState
    round: int
    status: str
    errors: Annotated[list[NodeError], operator.add]
    events: Annotated[list[Event], operator.add]
```

### 3.2 节点职责

| 节点 | 职责 | 失败降级 |
|---|---|---|
| `intake` | 校验用户/项目、加载 ACL、注入/越权检测 | 直接拒答 + 审计 |
| `link_entities` | 实体识别、别名、跨库 ID、物种/细胞 | 标记 ambiguous |
| `plan` | 拆子问题、选源、生成查询 | 规则模板兜底 |
| `retrieve_domain` | 分域混合检索 + ACL 过滤 | 单源失败不阻塞 |
| `call_tool` | 白名单只读工具 | 记为数据缺口 |
| `normalize` | 去重、实体对齐、stance 初判、定位 | stance=unknown |
| `graph_expand` | 1 跳图谱扩展 | 跳过 |
| `counter_evidence` | 反例/阴性检索 | 记录“未找到” |
| `grade` | A/B/C/D 证据分级 | 降为 D 并说明 |
| `synthesize` | 结构化 claims | 抽取式 claims |
| `verify` | 引用/ACL/quote/支持覆盖校验 | 删除或降级，最多修复 1 次 |
| `gaps` | 数据缺口与建议实验 | 规则模板 |
| `risk_route` | 自动完成 / 人工评审 | 默认人工评审 |
| `human_review` | `interrupt` / `Command(resume=...)` | 保持 pending |
| `finalize` | 渲染 Markdown + 快照 + 审计 | 保存草稿 |

### 3.3 预算

| 约束 | 默认 |
|---|---|
| `max_plan_rounds` | 2 |
| `max_subquestions` | 5 |
| `max_retrievals` | 12 |
| `max_tool_calls` | 4 |
| `max_llm_calls` | 12 |
| `max_task_seconds` | 180 |
| `max_evidence` | 40 |

停止条件：无新证据 / 子问题全覆盖 / 预算耗尽 / 高风险转人工。

---

## 4. 模型与 Embedding

| 用途 | 服务 | 模型 | 配置 |
|---|---|---|---|
| 生成 | 智谱 | `glm-4.7-flash` | base_url `https://open.bigmodel.cn/api/paas/v4/` |
| 降级 | 智谱 | `glm-4.5-flash` | 限流/失败时切换 |
| Embedding | 硅基流动 | `BAAI/bge-m3` | base_url `https://api.siliconflow.cn/v1`，1024 维 |
| Rerank（可选） | 硅基流动 | `BAAI/bge-reranker-v2-m3` | 默认关闭 |

注意：

- 智谱 `temperature` 必须落在 `(0, 1]`，默认 `0.1`；
- GLM-4.7-Flash 有限流，LLM 并发上限 2，指数退避，失败降级；
- Embedding 必须校验 1024 维、非全零、无 NaN；
- 换 Embedding 模型必须重建索引，manifest 记录模型与维度。

---

## 5. 数据设计

### 5.1 数据来源

| 数据 | 来源 | 许可 |
|---|---|---|
| 文献 | Europe PMC / PMC OA | 开放许可，逐篇记录 |
| 临床试验 | ClinicalTrials.gov API v2 | 公开数据 |
| 靶点证据 | Open Targets | CC BY 4.0（使用前确认） |
| 基因/蛋白/疾病/细胞 | NCBI Gene、UniProt、MONDO、CL | 开放 |
| 表达 | HPA、Expression Atlas、GEO 汇总 | 开放汇总 |
| 专利 | USPTO / EPO / 公共专利页 | 公开数据 |
| 内部 ELN/项目/ACL | 合成 | 标注 `DEMO / SYNTHETIC` |

### 5.2 第一版规模

- 100 篇论文（40 全文 + 60 摘要）；
- 20 件专利；
- 10 项临床试验；
- 3 个表达数据集；
- 15 条合成 ELN（含 4 条阴性）；
- 3 份合成项目报告；
- 30–40 条评估问题。

### 5.3 Manifest

每个文档至少记录：

```json
{
  "doc_id": "...",
  "source": "Europe PMC",
  "source_url": "...",
  "license": "CC BY 4.0",
  "retrieved_at": "2026-10-26",
  "content_hash": "sha256...",
  "source_type": "literature",
  "acl_scope": "public",
  "parse_status": "ok"
}
```

---

## 6. 检索与证据

### 6.1 科学切块

- 论文按章节，专利按权利要求/实施例，ELN 按实验记录，项目报告按章节；
- 父块保留完整上下文，子块 300–500 字；
- 表格整表保留表头；图注与正文绑定；
- 阴性结果必须保留 `result_polarity=negative`；
- `chunk_id = sha256(doc_id + page + section + chunk_index + text)`，重复运行稳定。

### 6.2 混合检索

```text
query
  → 实体别名扩展
  → dense top 20（ACL/物种/年份过滤）
  → BM25 top 20（同样过滤）
  → RRF 融合（k=60）
  → 可选 BGE rerank
  → 每子问题 top 8，按父块去重
```

不把 distance 转成伪百分比；保留原始分数。

### 6.3 ACL

- chunk 带单值 `acl_scope`：`public` 或 `project:IBD-TX-07`；
- 用户得到 `allowed_scopes`；
- Chroma `where={"acl_scope": {"$in": allowed_scopes}}`；
- BM25 侧 Python 同样过滤；
- 工具调用校验项目权限；
- 越权与不存在返回同一句话；
- 每次访问写审计日志。

### 6.4 证据分级

| 等级 | 判定 |
|---|---|
| A | 人体样本 + 直接终点 + 多队列/多方法一致 + 可重复 |
| B | 人体单队列，或动物模型 + 直接终点 + 一致 |
| C | 体外/单一方法/间接指标/小样本 |
| D | 专利声称无实施例 / 摘要性陈述 / 推测 / 冲突未解释 |

评分维度：直接性 30、物种 20、方法 15、重复性 15、样本量 10、一致性 10。等级由代码计算，LLM 不定级。

### 6.5 反例与引用

- 每个 claim 至少执行一次否定查询；
- 报告单列“反例与冲突”；
- claim 只引用本次 evidence 集合中的 `evidence_id`；
- 程序校验：id 存在、ACL 可访问、quote 是 chunk 子串、至少 1 条支持证据、反例必须列出；
- 引用列表由代码组装，模型不得生成文件名/页码。

---

## 7. API 与页面

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/research/tasks` | 创建任务 |
| GET | `/api/research/tasks/{id}` | 任务状态 |
| GET | `/api/research/tasks/{id}/result` | 研究底稿 |
| GET | `/api/research/tasks/{id}/events` | SSE 进度 |
| POST | `/api/research/tasks/{id}/review` | 人工评审 |
| GET | `/api/research/tasks/{id}/snapshot` | 快照 |
| GET | `/api/evidence/{id}` | 证据详情 |
| GET | `/api/knowledge/stats` | 索引统计 |
| POST | `/api/knowledge/rebuild` | 重建索引 |
| GET | `/api/health` | 健康检查 |

页面：研究工作台（问题输入、研究底稿、证据抽屉、节点时间线、评审按钮），Jinja2 + 原生 JS，无 CDN。

---

## 8. 测试与评估

- 单元：配置、解析、切块、实体链接、ACL、RRF、分级、引用校验、预算；
- 图：正常、冲突、无证据、越权、注入、单源失败、校验失败修复、评审恢复；
- API：任务、状态、结果、SSE、评审、错误映射；
- E2E：6 个演示问题 + 重建索引 + 页面；
- 评估：30–40 条标注问题。

| 指标 | 目标 |
|---|---|
| Recall@10 | ≥90% |
| 引用可验证率 | 程序校验 100% |
| 冲突覆盖率 | ≥85% |
| 实体链接准确率 | ≥95% |
| ACL 泄露 | 0 |
| 无答案拒答 | 100%，不调用 LLM |
| p95 延迟 | ≤60s |

---

## 9. 实施阶段

| 阶段 | 内容 |
|---|---|
| P0 | 环境、骨架、配置、SQLite、健康检查（已完成） |
| P1 | 抓取 100 篇 + 合成内部数据 + manifest |
| P2 | 本体/图谱、切块、BGE-M3 建库、BM25 |
| P3 | 混合检索 + RRF + 可选 rerank + 组学工具 |
| P4 | LangGraph 主图、fan-out、预算、SSE |
| P5 | 反例、分级、claims、引用校验、研究底稿 |
| P6 | FastAPI 业务接口 + 工作台页面 |
| P7 | 人工评审、快照、审计、权限测试 |
| P8 | 评估集、README、演示脚本、验收 |

---

## 10. 关键风险

| 风险 | 应对 |
|---|---|
| GLM-4.7-Flash 限流 | 并发 1–2、退避、降级 `glm-4.5-flash`、缓存 |
| 智谱 temperature=0 不支持 | 使用 0.1，配置层拒绝 0 |
| BGE-M3 返回异常向量 | 校验维度/非零/NaN，失败重试并报错 |
| 公开数据许可复杂 | 只取开放许可，逐篇 manifest，保留 attribution |
| 内部 ELN 无法公开获取 | 合成并明确标注 DEMO，不冒充真实数据 |
| 真实语料噪声 | 控制规模、人工标注评估集、先 100 篇跑通 |
| ACL 泄露 | 检索前过滤、生成后复核、统一拒答话术、审计 |
| 多步循环失控 | 预算 + 最大轮次 + 停止条件 |

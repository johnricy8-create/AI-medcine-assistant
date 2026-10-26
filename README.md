# 医药研发知识助手

基于 **LangChain + LangGraph** 的医药研发证据工作台。面向创新药项目科学家，把文献、专利、临床试验、内部 ELN、组学数据和项目报告连接起来，输出带证据等级、反例、数据缺口和可验证引用的研究底稿。

> 当前状态：**P0 环境与骨架完成**。已具备配置、SQLite 全链路表结构、健康检查和测试；检索、LangGraph、数据抓取、页面尚未实现。

---

## 1. 第一版目标

- 输入一个复杂研究问题，自动拆解子问题；
- 并行检索文献 / 专利 / ELN / 组学工具；
- 统一科学实体（靶点、基因、蛋白、疾病、细胞、化合物）；
- 主动检索反例与阴性结果；
- 输出结构化 claims、证据等级、冲突、数据缺口、建议实验；
- 每条结论可回到 DOI / 专利号 / ELN 实验 / 页码 / 章节；
- 项目 ACL 在检索时生效，越权不泄露存在性；
- 支持人工评审、版本快照和审计。

演示主线：**IBD（炎症性肠病）+ IL23R / NOD2**。公开文献、专利、临床试验和表达数据使用真实公开数据；企业内部 ELN、项目报告、ACL 使用合成数据并明确标注 `DEMO / SYNTHETIC`。

---

## 2. 技术栈

| 层 | 选型 |
|---|---|
| 语言 | Python 3.12 |
| 包管理 | uv |
| 编排 | LangGraph 1.0 |
| LLM 框架 | LangChain 1.2 |
| 生成模型 | 智谱 `glm-4.7-flash`（OpenAI 兼容） |
| Embedding | 硅基流动 `BAAI/bge-m3`（1024 维） |
| 向量库 | Chroma |
| 稀疏检索 | rank-bm25 + jieba |
| 图谱 | NetworkX |
| API | FastAPI + Uvicorn |
| 页面 | Jinja2 + 原生 CSS/JS（后续阶段） |
| 存储 | SQLite + 文件快照 |
| 测试 | unittest |

---

## 3. 环境准备

### 3.1 安装依赖

在项目根目录执行：

```powershell
uv sync
```

`uv` 会自动创建 `.venv` 并安装锁定依赖。

### 3.2 配置密钥

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，填入：

```dotenv
LLM_API_KEY=你的智谱Key
EMBEDDING_API_KEY=你的硅基流动Key
```

> 不要把 `.env` 提交到 Git。密钥只通过环境变量读取，不写入日志。

### 3.3 验证服务

```powershell
uv run python scripts/check_services.py
```

预期输出类似：

```text
[OK  ] SQLite     D:\医药研发助手\storage\app.db
[OK  ] LLM        glm-4.7-flash -> 连接成功
[OK  ] Embedding  BAAI/bge-m3 -> 1024 维
```

未配置 Key 时对应项显示 `SKIP`，不会阻塞本地开发。

---

## 4. 启动

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

打开：

- 健康检查：<http://127.0.0.1:8000/api/health>
- Swagger：<http://127.0.0.1:8000/docs>

健康检查不会调用外部模型，只报告配置与数据库状态。

---

## 5. 测试

```powershell
uv run python -m unittest discover -s tests -v
```

当前覆盖：

- 配置加载、路径解析、chunk 参数校验、temperature 约束；
- SQLite 初始化、幂等建表、外键约束、任务/证据写入；
- FastAPI 健康检查、数据库初始化、根路由。

---

## 6. 目录结构

```text
医药研发助手/
├─ app/
│  ├─ main.py              # FastAPI 入口
│  ├─ config.py            # pydantic-settings 配置
│  ├─ schemas.py           # 领域模型与枚举
│  ├─ api/
│  │  └─ health.py         # 健康检查
│  └─ storage/
│     ├─ db.py             # SQLite 连接与初始化
│     └─ schema.sql        # 任务/证据/claim/评审/快照/审计表
├─ data/                   # 语料、本体、ACL、评估集（后续）
├─ docs/                   # 设计文档（后续）
├─ scripts/
│  └─ check_services.py    # 真实 Key 连通性检查
├─ tests/
├─ storage/                # 运行时数据（gitignore）
├─ .env.example
├─ pyproject.toml
└─ README.md
```

---

## 7. 数据库表

| 表 | 用途 |
|---|---|
| `projects` / `project_members` | 项目与演示级 ACL |
| `documents` / `chunks` | 文档、切块、实体/物种/方法/ACL 元数据 |
| `research_tasks` | 研究任务与状态 |
| `task_events` | LangGraph 节点事件（SSE / 审计） |
| `evidence` | 任务证据集与定位信息 |
| `claims` | 结构化结论、支持/反例、等级、校验状态 |
| `reviews` | 科学家评审记录 |
| `snapshots` | 研究快照（索引/模型/Prompt/工具/证据版本） |
| `tool_calls` | 结构化工具调用与结果 hash |
| `audit_log` | 权限与访问审计 |
| `index_manifest` | 索引版本与 embedding 模型清单 |
| `llm_cache` | LLM 结果缓存，降低重复成本 |

---

## 8. 关键约束

1. **不自动重建索引**：只有 `scripts/rebuild_index.py` 或显式重建接口可以建库。
2. **无证据不调用 LLM**：检索阈值不通过时直接拒答。
3. **引用由程序组装**：模型只生成 claim 正文和 evidence_id，来源列表由代码根据真实检索结果生成。
4. **ACL 先于检索**：检索条件带 `acl_scope`，不是生成后再遮挡。
5. **智谱 temperature 不能用 0**：官方要求 `(0, 1]`，默认 `0.1`。
6. **GLM-4.7-Flash 有限流**：LangGraph fan-out 并发限制为 2，失败退避并降级到 `glm-4.5-flash`。
7. **数据许可**：只索引开放许可内容；逐篇记录 `source_url`、`license`、`retrieved_at`、`content_hash`。
8. **合成内部数据必须标注**：ELN/项目/ACL 为 `DEMO / SYNTHETIC`，不得冒充真实企业数据。

---

## 9. 后续阶段

| 阶段 | 内容 |
|---|---|
| P1 | 抓取 100 篇公开论文 + 20 专利 + 10 试验；合成 ELN/项目/ACL；manifest |
| P2 | 本体/图谱、科学切块、BGE-M3 建库、BM25 |
| P3 | 混合检索 + RRF + 可选 rerank + 组学工具 |
| P4 | LangGraph 主图、fan-out、预算、降级、SSE |
| P5 | 反例、证据分级、claims、引用校验、研究底稿 |
| P6 | FastAPI 业务接口 + 研究工作台页面 |
| P7 | 人工评审、快照、审计、权限测试 |
| P8 | 30–40 条评估、演示脚本、最终验收 |

---

## 10. 免责声明

本系统仅用于研究辅助与教学演示，不构成临床诊疗建议、医学判断或知识产权结论。系统输出的是研究假设与证据线索，实验验证、医学决策和专利审查必须由专业人员完成。

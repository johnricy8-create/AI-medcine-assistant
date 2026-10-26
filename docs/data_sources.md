# P1 数据来源与治理说明

> 生成日期：2026-10-26
> 对应阶段：P1（数据接入完成）
> 产物：`data/manifest.jsonl`（152 条）、`data/processed/documents.jsonl`（152 条）

---

## 1. 数据总量

| 来源 | 类型 | 数量 | 说明 |
|---|---|---|---|
| Europe PMC | 文献 | **100 篇** | 47 篇 OA 全文 + 53 篇摘要 |
| ClinicalTrials.gov | 临床试验 | 10 项 | IBD / UC / Crohn 相关 |
| Human Protein Atlas | 表达 | 2 条 | IL23R、NOD2；组织/单细胞/血细胞 |
| Open Targets | 靶点—疾病 | 2 条文档 | 43 个节点、50 条边 |
| 合成内部数据 | ELN | 15 条 | 含 7 条阴性/失败记录 |
| 合成内部数据 | 项目报告 | 3 份 | 含跨项目 ACL 示例 |
| 合成内部数据 | 专利 | 20 件 | `DEMO-PAT-*`，明确标注 |
| **合计** |  | **152 条标准化文档** |  |

---

## 2. 公开数据源

### 2.1 Europe PMC

- 接口：`https://www.ebi.ac.uk/europepmc/webservices/rest/search`
- 全文：`https://www.ebi.ac.uk/europepmc/webservices/rest/{PMCID}/fullTextXML`
- 检索策略：`TITLE_ABS` 限定标题/摘要，覆盖 IL23R、NOD2、IL-23、IBD、Crohn、UC、单细胞/活检等。
- 过滤：标题/摘要必须包含 IBD 相关词；按靶点匹配数和引用数排序。
- 全文：仅对 `isOpenAccess=Y` 且 `inPMC=Y` 的记录抓取；失败时回退到摘要。
- 长度：单篇入库文本上限 **80,000 字符**；23 篇超长指南被截断，`metadata.truncated=true`。
- 许可：逐篇记录 `license`；缺失标记 `unknown`。**生产前必须逐条复核许可**。

### 2.2 ClinicalTrials.gov

- 接口：`https://clinicaltrials.gov/api/v2/studies`
- 查询条件：`ulcerative colitis`、`Crohn disease`、`inflammatory bowel disease`
- 保留字段：NCT ID、标题、状态、phase、study type、入组数、条件、干预、主要终点、入排标准、申办方。
- 许可：ClinicalTrials.gov 公开数据。

### 2.3 Human Protein Atlas

- 接口：`https://www.proteinatlas.org/{ENSG}.json`
- 基因：IL23R（ENSG00000162594）、NOD2（ENSG00000167207）
- 字段：RNA tissue specific nTPM、single cell type specific nCPM、single cell group nCPM、blood cell nTPM。
- 许可：CC BY 4.0。

### 2.4 Open Targets Platform

- 接口：`https://api.platform.opentargets.org/api/v4/graphql`（POST）
- 查询：IL23R / NOD2 的 `associatedDiseases`，每个靶点 25 条。
- 产物：`data/processed/graph/nodes.jsonl`、`edges.jsonl`。
- 许可：CC BY 4.0（使用前请再次确认平台条款）。

### 2.5 本体

- `data/ontology/entities.yaml`
- ID 来源：Ensembl、UniProt、NCBI Gene、MONDO、Cell Ontology。
- 已核验：
  - IL23R：ENSG00000162594 / Q5VWK5 / NCBI 149233
  - NOD2：ENSG00000167207 / Q9HC29 / NCBI 64127
  - IL23A：ENSG00000110944 / Q9NPF7 / NCBI 51561
  - IL12B：ENSG00000113302 / P29460 / NCBI 3593
  - IBD：MONDO_0005265；Crohn：MONDO_0005011；UC：MONDO_0005101
  - CD4+ memory T：CL_0000897；Treg：CL_0000815；ILC3：CL_0001069；Paneth：CL_0000510

---

## 3. 合成内部数据

> 所有合成记录都带 `DEMO / SYNTHETIC` 标记，不冒充真实企业数据。

| 文件 | 内容 |
|---|---|
| `data/internal_demo/eln.jsonl` | 15 条 ELN，含 7 条阴性/失败记录 |
| `data/internal_demo/projects.json` | 3 份项目报告 |
| `data/internal_demo/patents.json` | 20 件合成专利 |
| `data/internal_demo/acl/users.yaml` | 4 个演示用户 |
| `data/internal_demo/acl/projects.yaml` | 2 个项目空间 |

演示用户：

| 用户 | 可见范围 |
|---|---|
| `scientist_031` | `public` + `project:IBD-TX-07` |
| `scientist_045` | `public` + `project:ONCO-02` |
| `reviewer_001` | 两个项目都可见 |
| `guest` | 仅 `public` |

关键演示点：

- `ELN-2019-881`：小鼠 DSS 模型 IL23R 蛋白阴性；
- `ELN-2024-003`：T 细胞转移模型 IL23R 蛋白阴性；
- `ELN-2021-044` / `ELN-2023-055` / `ELN-2025-019`：人 IBD 组织阳性；
- `ELN-2023-020` / `ELN-2025-012`：NOD2 敲低/敲除对 IL23R 阴性；
- `ELN-ONCO-2024-777`：ONCO-02 项目，用于越权测试；
- `DEMO-PAT-007`：有权利要求但无实施例，用于 D 级证据演示。

---

## 4. 专利限制与后续替换

当前网络环境下：

- PatentsView 旧接口已迁移到需认证的 Open Data Portal；
- USPTO API 返回 401；
- EPO OPS 返回 403（Fair Use）；
- Google Patents 请求超时；
- WIPO PATENTSCOPE 结果为 JSF 动态加载，不适合稳定抓取。

因此第一版使用 20 件合成专利，保留以下接口设计：

```text
app/ingest/patents.py（后续）
  - EPO OPS adapter（需 EPO_OPS_KEY）
  - USPTO Open Data adapter（需 USPTO_API_KEY）
  - 统一输出 NormalizedDocument(source_type=patent)
```

替换真实专利后，只需重新生成本地索引，不影响检索与 LangGraph 层。

---

## 5. 数据治理规则

1. 只抓公开/开放许可内容；不抓付费墙、受控访问患者数据。
2. 每个文档必须有 `source`、`source_url`、`license`、`retrieved_at`、`content_hash`。
3. `data/raw/` 与 `data/processed/` 不提交 Git；`manifest.jsonl` 与合成内部数据提交。
4. 合成数据必须在标题和正文中标注 `DEMO / SYNTHETIC`。
5. 全文入库上限 80,000 字符；超长文档标记 `truncated=true`。
6. 生产前复核 Europe PMC `license=unknown` 的 51 篇摘要。
7. 不把合成 ELN 结果当作真实科学结论；报告中必须显示来源类型与 DEMO 标记。

---

## 6. 刷新方式

```powershell
# 完整刷新（公开 + 合成）
uv run python scripts/fetch_data.py

# 只刷新合成内部数据
uv run python scripts/seed_internal_demo.py

# 只刷新公开数据
uv run python scripts/fetch_data.py --skip-synthetic
```

`manifest.jsonl` 与 `documents.jsonl` 均按 `doc_id` 幂等合并，重复运行不会产生重复记录。

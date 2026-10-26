"""合成内部演示数据：ELN、项目报告、未公开专利、ACL。

这些数据用于演示 07 案例的核心能力：
- 内部阴性实验与失败记录；
- 项目权限隔离；
- 公开证据与内部证据的冲突；
- 专利声称但无实施例的证据等级差异。

所有记录都带 DEMO / SYNTHETIC 标记，不冒充真实企业数据。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from app.ingest.manifest import write_json, write_jsonl
from app.ingest.models import DocumentSection, FetchedDocument, NormalizedDocument
from app.schemas import SourceType

DEMO_NOTICE = "DEMO / SYNTHETIC — 仅用于教学演示，不是真实企业实验记录。"

PROJECTS = [
    {
        "project_id": "IBD-TX-07",
        "name": "IBD 靶点验证",
        "description": "炎症性肠病（IBD）新型靶点验证项目，演示用项目空间。",
        "acl_scope": "project:IBD-TX-07",
    },
    {
        "project_id": "ONCO-02",
        "name": "肿瘤免疫探索",
        "description": "肿瘤免疫微环境探索项目，用于演示跨项目权限隔离。",
        "acl_scope": "project:ONCO-02",
    },
]

USERS = [
    {
        "user_id": "scientist_031",
        "name": "项目科学家 A",
        "groups": ["IBD-TX-07"],
        "allowed_scopes": ["public", "project:IBD-TX-07"],
    },
    {
        "user_id": "scientist_045",
        "name": "项目科学家 B",
        "groups": ["ONCO-02"],
        "allowed_scopes": ["public", "project:ONCO-02"],
    },
    {
        "user_id": "reviewer_001",
        "name": "评审专家",
        "groups": ["IBD-TX-07", "ONCO-02"],
        "allowed_scopes": ["public", "project:IBD-TX-07", "project:ONCO-02"],
    },
    {
        "user_id": "guest",
        "name": "只读访客",
        "groups": [],
        "allowed_scopes": ["public"],
    },
]

ELN_RECORDS: list[dict[str, Any]] = [
    {
        "experiment_id": "ELN-2019-881",
        "project_id": "IBD-TX-07",
        "target": "IL23R",
        "title": "IL23R 蛋白在 DSS 结肠炎小鼠模型中的表达",
        "species": "Mus musculus",
        "sample": "colon tissue",
        "cell_type": "bulk colon",
        "method": "Western blot",
        "conditions": "C57BL/6J，3% DSS 7 天，n=8/组；第 10 天取材。",
        "result": "IL23R 蛋白在 DSS 组与对照组之间未见显著差异（p=0.41）。",
        "result_polarity": "negative",
        "conclusion": "在该模型和蛋白水平上未观察到 IL23R 升高；不能排除时间点、抗体特异性或样本量影响。",
        "date": "2019-11-14",
        "acl_scope": "project:IBD-TX-07",
    },
    {
        "experiment_id": "ELN-2021-044",
        "project_id": "IBD-TX-07",
        "target": "IL23R",
        "title": "人 IBD 活检组织 IL23R mRNA 表达",
        "species": "Homo sapiens",
        "sample": "intestinal biopsy",
        "cell_type": "bulk mucosa",
        "method": "qPCR",
        "conditions": "活动期 UC 18 例、缓解期 12 例、非 IBD 对照 15 例；炎症与非炎症部位配对。",
        "result": "活动期 UC 炎症部位 IL23R mRNA 较非炎症部位升高 2.1 倍（p=0.006）。",
        "result_polarity": "positive",
        "conclusion": "支持 IL23R 在活动期 UC 炎症黏膜中转录水平升高；样本量有限，需独立队列复现。",
        "date": "2021-06-03",
        "acl_scope": "project:IBD-TX-07",
    },
    {
        "experiment_id": "ELN-2022-117",
        "project_id": "IBD-TX-07",
        "target": "IL23R",
        "title": "CD4+ 记忆 T 细胞亚群 IL23R 流式检测",
        "species": "Homo sapiens",
        "sample": "PBMC / lamina propria lymphocytes",
        "cell_type": "CD4+ memory T cells",
        "method": "flow cytometry",
        "conditions": "IBD 患者 12 例、对照 10 例；表面 IL23R 与 CD45RO、CCR6、CD127 共染。",
        "result": "IBD 组 CD4+CD45RO+CCR6+ 细胞中 IL23R+ 比例升高（11.4% vs 5.8%，p=0.02）。",
        "result_polarity": "positive",
        "conclusion": "支持 IL23R 在致病相关 CD4+ 记忆 T 细胞亚群中富集；流式抗体批次间差异需校正。",
        "date": "2022-09-21",
        "acl_scope": "project:IBD-TX-07",
    },
    {
        "experiment_id": "ELN-2023-020",
        "project_id": "IBD-TX-07",
        "target": "NOD2",
        "title": "NOD2 敲低对肠道类器官 IL23R 表达的影响",
        "species": "Homo sapiens",
        "sample": "intestinal organoid",
        "cell_type": "epithelial organoid",
        "method": "qPCR",
        "conditions": "回肠类器官，NOD2 siRNA 48h，L18-MDP 刺激 6h，n=4 供体。",
        "result": "NOD2 敲低效率 78%，IL23R mRNA 未见显著变化（p=0.63）。",
        "result_polarity": "negative",
        "conclusion": "在该类器官模型中未观察到 NOD2 对 IL23R 转录的直接影响。",
        "date": "2023-02-08",
        "acl_scope": "project:IBD-TX-07",
    },
    {
        "experiment_id": "ELN-2023-055",
        "project_id": "IBD-TX-07",
        "target": "IL23R",
        "title": "UC 结肠活检 IL23R RNA-seq 差异表达",
        "species": "Homo sapiens",
        "sample": "colonic biopsy",
        "cell_type": "bulk mucosa",
        "method": "RNA-seq",
        "conditions": "活动期 UC 24 例、对照 20 例；DESeq2 校正年龄、性别和批次。",
        "result": "IL23R 在活动期 UC 上调 log2FC=1.35，FDR=0.004；IL23A 上调 log2FC=1.02。",
        "result_polarity": "positive",
        "conclusion": "独立队列支持 IL23R/IL23A 在活动期 UC 中上调；需注意 bulk 组织细胞组成差异。",
        "date": "2023-07-19",
        "acl_scope": "project:IBD-TX-07",
    },
    {
        "experiment_id": "ELN-2024-003",
        "project_id": "IBD-TX-07",
        "target": "IL23R",
        "title": "T 细胞转移性结肠炎模型 IL23R 蛋白定量",
        "species": "Mus musculus",
        "sample": "colon tissue",
        "cell_type": "bulk colon / sorted T cells",
        "method": "Western blot",
        "conditions": "CD45RBhigh CD4+ T 细胞转移模型，n=6/组；供体鼠与受体鼠分别检测。",
        "result": "结肠组织 IL23R 蛋白未升高（p=0.52）；分选 T 细胞中亦未见差异。",
        "result_polarity": "negative",
        "conclusion": "在该小鼠模型中未复现 IL23R 蛋白升高；与人体 RNA 证据存在物种/方法差异。",
        "date": "2024-01-16",
        "acl_scope": "project:IBD-TX-07",
    },
    {
        "experiment_id": "ELN-2024-018",
        "project_id": "IBD-TX-07",
        "target": "IL23R",
        "title": "Treg 与 Teff 的 IL23R 表达比较",
        "species": "Homo sapiens",
        "sample": "PBMC",
        "cell_type": "Treg / conventional T cells",
        "method": "flow cytometry",
        "conditions": "健康供体 8 例；CD4+CD25hiCD127low Treg 与 CD4+CD25- Teff 对照。",
        "result": "Treg 的 IL23R+ 比例低于 Teff（3.1% vs 9.7%，p=0.008）。",
        "result_polarity": "negative",
        "conclusion": "外周血 Treg 的 IL23R 表达较低；组织内 Treg 是否不同需另做验证。",
        "date": "2024-04-11",
        "acl_scope": "project:IBD-TX-07",
    },
    {
        "experiment_id": "ELN-2024-031",
        "project_id": "IBD-TX-07",
        "target": "IL23R",
        "title": "人 PBMC 表面 IL23R 可检测性验证",
        "species": "Homo sapiens",
        "sample": "PBMC",
        "cell_type": "monocytes / T cells / B cells",
        "method": "flow cytometry",
        "conditions": "健康供体 6 例；两种克隆号抗体平行比较。",
        "result": "PBMC 表面 IL23R 信号接近同型对照，两种抗体结果不一致。",
        "result_polarity": "inconclusive",
        "conclusion": "PBMC 表面 IL23R 流式检测不可靠；后续优先使用组织样本或转录水平。",
        "date": "2024-07-02",
        "acl_scope": "project:IBD-TX-07",
    },
    {
        "experiment_id": "ELN-2025-007",
        "project_id": "IBD-TX-07",
        "target": "IL23R",
        "title": "IL-23 刺激肠道类器官 IL23R 反馈调节",
        "species": "Homo sapiens",
        "sample": "intestinal organoid",
        "cell_type": "epithelial organoid",
        "method": "qPCR",
        "conditions": "回肠类器官，IL-23 10 ng/mL 刺激 6h/24h，n=3 供体。",
        "result": "IL23R mRNA 在 6h 和 24h 均未显著变化（p>0.4）。",
        "result_polarity": "negative",
        "conclusion": "上皮类器官中未见 IL-23 对 IL23R 的短期反馈调节。",
        "date": "2025-01-22",
        "acl_scope": "project:IBD-TX-07",
    },
    {
        "experiment_id": "ELN-2025-012",
        "project_id": "IBD-TX-07",
        "target": "NOD2",
        "title": "NOD2 KO THP-1 细胞 IL23R 表达",
        "species": "Homo sapiens",
        "sample": "THP-1 cell line",
        "cell_type": "monocytic cell line",
        "method": "qPCR / Western blot",
        "conditions": "NOD2 KO 与野生型 THP-1，PMA 分化 48h，L18-MDP 刺激。",
        "result": "NOD2 KO 后 IL23R mRNA 与蛋白均无显著变化（p>0.5）。",
        "result_polarity": "negative",
        "conclusion": "单核细胞系中 NOD2 缺失不足以改变 IL23R 表达。",
        "date": "2025-03-05",
        "acl_scope": "project:IBD-TX-07",
    },
    {
        "experiment_id": "ELN-2025-019",
        "project_id": "IBD-TX-07",
        "target": "IL23R",
        "title": "Crohn 病回肠组织 IL23R 免疫组化",
        "species": "Homo sapiens",
        "sample": "ileal biopsy",
        "cell_type": "lamina propria immune cells",
        "method": "IHC",
        "conditions": "Crohn 病 15 例、对照 10 例；染色强度由两位病理医师盲法评分。",
        "result": "Crohn 病组 lamina propria 单个核细胞 IL23R 染色评分升高（p=0.03）。",
        "result_polarity": "positive",
        "conclusion": "蛋白水平支持 IL23R 在 Crohn 病回肠炎症区域升高；抗体特异性仍需质控。",
        "date": "2025-06-18",
        "acl_scope": "project:IBD-TX-07",
    },
    {
        "experiment_id": "ELN-2025-024",
        "project_id": "IBD-TX-07",
        "target": "NOD2",
        "title": "NOD2 蛋白在 DSS 结肠炎中的动态变化",
        "species": "Mus musculus",
        "sample": "colon tissue",
        "cell_type": "bulk colon",
        "method": "Western blot",
        "conditions": "DSS 0/3/7/10 天取材，n=5/时间点。",
        "result": "NOD2 蛋白在第 7 天短暂下降，但第 10 天恢复，整体无显著差异（p=0.18）。",
        "result_polarity": "negative",
        "conclusion": "未观察到稳定的 NOD2 蛋白上调或下调。",
        "date": "2025-08-27",
        "acl_scope": "project:IBD-TX-07",
    },
    {
        "experiment_id": "ELN-2026-002",
        "project_id": "IBD-TX-07",
        "target": "IL23R",
        "title": "UC 结肠单细胞图谱 IL23R 细胞类型定位",
        "species": "Homo sapiens",
        "sample": "colonic biopsy",
        "cell_type": "single-cell suspension",
        "method": "single-cell RNA-seq",
        "conditions": "活动期 UC 6 例、对照 4 例；10x Genomics，约 48,000 个细胞。",
        "result": "IL23R 主要富集于 CD4+ 记忆 T 细胞与 ILC3 样细胞；上皮细胞几乎不表达。",
        "result_polarity": "positive",
        "conclusion": "支持 IL23R 的免疫细胞来源，而非上皮细胞；需注意解离偏差。",
        "date": "2026-01-14",
        "acl_scope": "project:IBD-TX-07",
    },
    {
        "experiment_id": "ELN-2026-009",
        "project_id": "IBD-TX-07",
        "target": "IL23R",
        "title": "组织 Treg 与 Teff IL23R 共表达验证",
        "species": "Homo sapiens",
        "sample": "colonic biopsy",
        "cell_type": "Treg / Teff",
        "method": "flow cytometry",
        "conditions": "IBD 患者 9 例；组织消化后 CD4+CD25hiCD127low 与 CD4+CD25- 分群。",
        "result": "组织 Treg 中 IL23R+ 比例为 14.2%，Teff 为 18.5%，差异未达显著（p=0.11）。",
        "result_polarity": "inconclusive",
        "conclusion": "组织内 Treg/Teff 的 IL23R 差异不明确；与外周血结果不完全一致。",
        "date": "2026-03-09",
        "acl_scope": "project:IBD-TX-07",
    },
    {
        "experiment_id": "ELN-ONCO-2024-777",
        "project_id": "ONCO-02",
        "target": "IL23R",
        "title": "肿瘤浸润淋巴细胞 IL23R 表达探索",
        "species": "Homo sapiens",
        "sample": "tumor tissue",
        "cell_type": "tumor-infiltrating lymphocytes",
        "method": "flow cytometry",
        "conditions": "实体瘤 8 例；与配对外周血比较。",
        "result": "肿瘤浸润 CD4+ T 细胞 IL23R+ 比例升高（16.8% vs 6.1%，p=0.01）。",
        "result_polarity": "positive",
        "conclusion": "ONCO-02 项目内部探索结果；与 IBD 项目权限隔离。",
        "date": "2024-10-30",
        "acl_scope": "project:ONCO-02",
    },
]

PROJECT_REPORTS = [
    {
        "report_id": "PRJ-IBD-2026-01",
        "project_id": "IBD-TX-07",
        "title": "IL23R 靶点证据综述与下一步验证建议",
        "sections": [
            (
                "Background",
                "IL23R 是 IL-23 受体复合物的重要组成部分，GWAS 与功能研究均提示其参与 IBD 发病。"
                "项目组需要区分人体转录水平、蛋白水平、细胞类型定位和动物模型证据。",
            ),
            (
                "Internal findings",
                "内部 qPCR/RNA-seq/IHC 多为人 IBD 组织阳性；但 ELN-2019-881 与 ELN-2024-003 在两种小鼠模型中未观察到 IL23R 蛋白升高。"
                "ELN-2024-018 显示外周血 Treg 的 IL23R 低于 Teff，而 ELN-2026-009 在组织内未复现该差异。",
            ),
            (
                "Interpretation",
                "现有证据支持“人 IBD 炎症黏膜中 IL23R 转录/蛋白升高，主要位于 CD4+ 记忆 T 细胞和 ILC3 样细胞”，"
                "但物种差异、抗体特异性和组织消化偏差使蛋白层面证据仍不稳健。",
            ),
            (
                "Recommendation",
                "建议在标准化分选和抗体质控条件下，优先复现人 IBD 组织 CD4+ 记忆 T 细胞的表面 IL23R 蛋白检测；"
                "暂不将小鼠蛋白阴性结果外推为人体无效。",
            ),
            (
                "Data gaps",
                "缺少统一实验条件下的蛋白水平验证、缺少独立队列的 Treg/Teff 对照、缺少 IL23R 与 IL23A 的空间共定位。",
            ),
        ],
        "acl_scope": "project:IBD-TX-07",
    },
    {
        "report_id": "PRJ-IBD-2026-02",
        "project_id": "IBD-TX-07",
        "title": "NOD2 与 IL23R 通路交叉验证计划",
        "sections": [
            (
                "Background",
                "NOD2 是 IBD 最重要的易感基因之一，主要通过 innate immune 与 autophagy 通路发挥作用；"
                "项目组提出 NOD2 可能间接调节 IL23R/IL-23 轴。",
            ),
            (
                "Internal findings",
                "ELN-2023-020 在肠道类器官中未观察到 NOD2 敲低对 IL23R 转录的影响；"
                "ELN-2025-012 在 THP-1 中同样为阴性；ELN-2025-024 未观察到小鼠结肠 NOD2 蛋白稳定变化。",
            ),
            (
                "Interpretation",
                "现有内部数据不支持 NOD2 对 IL23R 的强直接调控，但不能排除细胞类型、刺激条件和时间窗口的影响。",
            ),
            (
                "Recommendation",
                "优先在原代单核细胞/树突状细胞和 IBD 患者类器官中重复 MDP 刺激实验；"
                "同时用公共 Open Targets 遗传证据评估 NOD2–IL23R 通路的独立性。",
            ),
            (
                "Data gaps",
                "缺少原代免疫细胞、缺少剂量/时间曲线、缺少蛋白互作与分泌因子检测。",
            ),
        ],
        "acl_scope": "project:IBD-TX-07",
    },
    {
        "report_id": "PRJ-ONCO-2024-03",
        "project_id": "ONCO-02",
        "title": "IL23R 在肿瘤浸润淋巴细胞中的探索性分析",
        "sections": [
            (
                "Background",
                "ONCO-02 项目探索 IL23R 在肿瘤免疫微环境中的潜在价值，与 IBD 项目共享靶点但数据隔离。",
            ),
            (
                "Internal findings",
                "ELN-ONCO-2024-777 显示肿瘤浸润 CD4+ T 细胞 IL23R+ 比例升高；样本量 8 例，未做独立验证。",
            ),
            (
                "Recommendation",
                "仅在 ONCO-02 项目空间内可见；对外分享需知识产权与合规审批。",
            ),
        ],
        "acl_scope": "project:ONCO-02",
    },
]

PATENT_TOPICS = [
    ("IL23R", "Methods for treating intestinal inflammation by modulating IL23R signaling"),
    ("IL23R", "Anti-IL23R antibodies and uses thereof in inflammatory bowel disease"),
    ("IL23R", "Biomarkers for predicting response to IL-23 receptor blockade"),
    ("IL23R", "Small molecule inhibitors of IL-23 receptor complex assembly"),
    ("IL23R", "IL23R variant genotyping for IBD risk stratification"),
    ("IL23R", "Combination therapy comprising IL-23 and TNF-alpha inhibitors"),
    ("NOD2", "NOD2 agonists for enhancing mucosal innate immunity"),
    ("NOD2", "Methods of diagnosing Crohn's disease using NOD2 variants"),
    ("NOD2", "NOD2-targeted autophagy modulators"),
    ("NOD2", "Compositions for restoring NOD2 function in Paneth cells"),
    ("IL23R/NOD2", "Composite genetic score for inflammatory bowel disease"),
    ("IL23R", "IL23R-targeted CAR-T cells for autoimmune disease"),
    ("IL23R", "Sustained-release formulations of IL-23 receptor antagonists"),
    ("IL23R", "Methods for identifying IL23R-expressing T cell subsets"),
    ("NOD2", "NOD2 biomarker panel for predicting anti-TNF response"),
    ("IL23R", "Bispecific antibodies targeting IL23R and IL12Rbeta1"),
    ("IL23R", "IL23R expression modulators for treating ulcerative colitis"),
    ("NOD2", "NOD2 knockout organoids and drug screening methods"),
    ("IL23R", "RNA-based therapeutics targeting IL23R in IBD"),
    ("IL23R/NOD2", "Machine learning model integrating IL23R and NOD2 variants"),
]


def seed_internal_demo(data_dir: Path) -> list[FetchedDocument]:
    demo_dir = data_dir / "internal_demo"
    acl_dir = demo_dir / "acl"
    acl_dir.mkdir(parents=True, exist_ok=True)

    (acl_dir / "projects.yaml").write_text(
        yaml.safe_dump({"projects": PROJECTS}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (acl_dir / "users.yaml").write_text(
        yaml.safe_dump({"users": USERS}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    write_jsonl(demo_dir / "eln.jsonl", ELN_RECORDS)
    write_json(demo_dir / "projects.json", PROJECT_REPORTS)
    patents = _build_patents()
    write_json(demo_dir / "patents.json", patents)

    fetched: list[FetchedDocument] = []
    for record in ELN_RECORDS:
        fetched.append(
            FetchedDocument(
                document=_eln_document(record),
                source="Synthetic DEMO",
                raw_path=str(demo_dir / "eln.jsonl"),
                parse_status="ok_synthetic",
            )
        )
    for report in PROJECT_REPORTS:
        fetched.append(
            FetchedDocument(
                document=_report_document(report),
                source="Synthetic DEMO",
                raw_path=str(demo_dir / "projects.json"),
                parse_status="ok_synthetic",
            )
        )
    for patent in patents:
        fetched.append(
            FetchedDocument(
                document=_patent_document(patent),
                source="Synthetic DEMO",
                raw_path=str(demo_dir / "patents.json"),
                parse_status="ok_synthetic",
            )
        )
    return fetched


def _build_patents() -> list[dict[str, Any]]:
    patents: list[dict[str, Any]] = []
    for index, (target, title) in enumerate(PATENT_TOPICS, start=1):
        patent_no = f"DEMO-PAT-{index:03d}"
        claims = [
            f"1. A method of treating inflammatory bowel disease in a subject, comprising administering a therapeutically effective amount of a {target} modulator.",
            f"2. The method of claim 1, wherein the {target} modulator is an antibody or antigen-binding fragment.",
            "3. The method of claim 1, wherein the subject has ulcerative colitis or Crohn's disease.",
            f"4. A biomarker panel comprising at least one {target} expression marker.",
        ]
        embodiments = [
            (
                "Example 1: In vitro assay. "
                f"Primary human CD4+ T cells were stimulated with IL-23 and treated with a {target} modulator. "
                "Cytokine secretion was measured by ELISA. "
                "The example is synthetic and illustrative only."
            ),
            (
                "Example 2: Animal model. "
                "A chronic colitis model was used to assess clinical score and histology. "
                "No numerical data are provided in this synthetic record."
            ),
        ]
        acl_scope = "public"
        project_id = None
        if index == 5:
            acl_scope = "project:IBD-TX-07"
            project_id = "IBD-TX-07"
        if index == 12:
            acl_scope = "project:ONCO-02"
            project_id = "ONCO-02"
        if index == 7:
            embodiments = []
        patents.append(
            {
                "patent_no": patent_no,
                "title": title,
                "abstract": (
                    f"Disclosed are compositions and methods related to {target} signaling in intestinal inflammation. "
                    "The disclosure claims therapeutic, diagnostic and biomarker uses. "
                    "This is a synthetic patent record for a teaching demo."
                ),
                "claims": claims,
                "embodiments": embodiments,
                "assignee": "Qiyuan Bio (fictional)",
                "public_date": f"202{2 + index % 4}-{1 + index % 12:02d}-15",
                "jurisdiction": "WO",
                "acl_scope": acl_scope,
                "project_id": project_id,
            }
        )
    return patents


def _eln_document(record: dict[str, Any]) -> NormalizedDocument:
    title = f"[DEMO] {record['experiment_id']} {record['title']}"
    sections = [
        DocumentSection(heading="Objective", text=record["title"], kind="objective"),
        DocumentSection(heading="Conditions", text=record["conditions"], kind="conditions"),
        DocumentSection(heading="Method", text=record["method"], kind="method"),
        DocumentSection(heading="Results", text=record["result"], kind="results"),
        DocumentSection(heading="Conclusion", text=record["conclusion"], kind="conclusion"),
    ]
    text = "\n\n".join(
        f"{DEMO_NOTICE}\n\n{section.heading}\n{section.text}" if index == 0 else f"{section.heading}\n{section.text}"
        for index, section in enumerate(sections)
    )
    document = NormalizedDocument(
        doc_id=f"eln:{record['experiment_id']}",
        source_type=SourceType.ELN,
        source_id=record["experiment_id"],
        title=title,
        text=f"{title}\n\n{text}",
        sections=sections,
        abstract=record["result"],
        year=_year(record["date"]),
        license="DEMO-SYNTHETIC",
        acl_scope=record["acl_scope"],
        project_id=record["project_id"],
        species=record["species"],
        sample=record["sample"],
        method=record["method"],
        result_polarity=record["result_polarity"],
        entity_ids=_entity_ids(record["target"]),
        metadata={
            "synthetic": True,
            "demo_notice": DEMO_NOTICE,
            "experiment_id": record["experiment_id"],
            "project_id": record["project_id"],
            "target": record["target"],
            "cell_type": record["cell_type"],
            "date": record["date"],
            "result": record["result"],
            "result_polarity": record["result_polarity"],
            "conclusion": record["conclusion"],
        },
    )
    return document.finalize()


def _report_document(report: dict[str, Any]) -> NormalizedDocument:
    title = f"[DEMO] {report['report_id']} {report['title']}"
    sections = [
        DocumentSection(heading=heading, text=text, kind="report")
        for heading, text in report["sections"]
    ]
    text = "\n\n".join(
        f"{DEMO_NOTICE}\n\n{section.heading}\n{section.text}" if index == 0 else f"{section.heading}\n{section.text}"
        for index, section in enumerate(sections)
    )
    document = NormalizedDocument(
        doc_id=f"report:{report['report_id']}",
        source_type=SourceType.REPORT,
        source_id=report["report_id"],
        title=title,
        text=f"{title}\n\n{text}",
        sections=sections,
        abstract=report["sections"][0][1],
        license="DEMO-SYNTHETIC",
        acl_scope=report["acl_scope"],
        project_id=report["project_id"],
        species="Homo sapiens",
        sample="internal project report",
        method="evidence review",
        entity_ids=_entity_ids(report["title"]),
        metadata={
            "synthetic": True,
            "demo_notice": DEMO_NOTICE,
            "report_id": report["report_id"],
            "project_id": report["project_id"],
        },
    )
    return document.finalize()


def _patent_document(patent: dict[str, Any]) -> NormalizedDocument:
    title = f"[DEMO] {patent['patent_no']} {patent['title']}"
    claims_text = "\n".join(patent["claims"])
    embodiments_text = "\n".join(patent["embodiments"]) or "No embodiments disclosed."
    sections = [
        DocumentSection(heading="Abstract", text=patent["abstract"], kind="abstract"),
        DocumentSection(heading="Claims", text=claims_text, kind="claims"),
        DocumentSection(heading="Embodiments", text=embodiments_text, kind="embodiments"),
    ]
    text = "\n\n".join(
        f"{DEMO_NOTICE}\n\n{section.heading}\n{section.text}" if index == 0 else f"{section.heading}\n{section.text}"
        for index, section in enumerate(sections)
    )
    document = NormalizedDocument(
        doc_id=f"patent:{patent['patent_no']}",
        source_type=SourceType.PATENT,
        source_id=patent["patent_no"],
        title=title,
        text=f"{title}\n\n{text}",
        sections=sections,
        abstract=patent["abstract"],
        year=_year(patent["public_date"]),
        license="DEMO-SYNTHETIC",
        acl_scope=patent["acl_scope"],
        project_id=patent["project_id"],
        species="Homo sapiens",
        sample="patent disclosure",
        method="patent claims",
        entity_ids=_entity_ids(patent["title"]),
        metadata={
            "synthetic": True,
            "demo_notice": DEMO_NOTICE,
            "patent_no": patent["patent_no"],
            "assignee": patent["assignee"],
            "public_date": patent["public_date"],
            "jurisdiction": patent["jurisdiction"],
            "has_embodiments": bool(patent["embodiments"]),
        },
    )
    return document.finalize()


def _entity_ids(text: str) -> list[str]:
    lower = text.lower()
    ids: list[str] = []
    if "il23r" in lower or "il-23r" in lower:
        ids.append("ENSG00000162594")
    if "nod2" in lower or "card15" in lower:
        ids.append("ENSG00000167207")
    if "ibd" in lower or "inflammatory bowel" in lower:
        ids.append("MONDO_0005265")
    if "crohn" in lower:
        ids.append("MONDO_0005011")
    if "ulcerative colitis" in lower:
        ids.append("MONDO_0005101")
    return ids


def _year(value: str | None) -> int | None:
    if value and len(value) >= 4 and value[:4].isdigit():
        return int(value[:4])
    return None

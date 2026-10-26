"""临时 API 端到端冒烟（不提交）。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8010"
USER = "scientist_031"


def poll(client: httpx.Client, task_id: str, timeout: float = 180) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/research/tasks/{task_id}")
        response.raise_for_status()
        data = response.json()
        if data["status"] in {
            "completed",
            "no_evidence",
            "blocked",
            "budget_exhausted",
            "failed",
            "rejected",
        }:
            return data
        time.sleep(1)
    raise TimeoutError(task_id)


def run_case(client: httpx.Client, name: str, question: str, project: str) -> dict:
    created = client.post(
        "/api/research/tasks",
        json={
            "project_id": project,
            "question": question,
            "sources": ["literature", "patent", "eln", "report", "omics", "trial"],
            "require_human_review": True,
        },
    )
    created.raise_for_status()
    task_id = created.json()["task_id"]
    status = poll(client, task_id)
    result = client.get(f"/api/research/tasks/{task_id}/result")
    if result.status_code != 200:
        result_data = {"status": status["status"], "error": result.text}
    else:
        result_data = result.json()
    evidence = result_data.get("evidence") or []
    claims = result_data.get("claims") or []
    print("\n===", name, "===")
    print("task", task_id, "status", result_data.get("status"))
    print("assessment", result_data.get("assessment"))
    print("evidence", len(evidence), "claims", len(claims))
    for claim in claims[:5]:
        print(
            " -",
            claim.get("stance"),
            claim.get("level"),
            "verified" if claim.get("verified") else "unverified",
            claim.get("text", "")[:110],
        )
        print("   support", claim.get("support_ids"), "contra", claim.get("contradict_ids"))
    print("errors", result_data.get("error"))
    return {
        "name": name,
        "task_id": task_id,
        "status": result_data.get("status"),
        "assessment": result_data.get("assessment"),
        "evidence_count": len(evidence),
        "claim_count": len(claims),
        "claims": claims,
        "report_head": (result_data.get("report_md") or "")[:800],
    }


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=60)
    page = client.get("/")
    print("PAGE", page.status_code, "研究底稿" in page.text)
    print("HEALTH", client.get("/api/health").json())
    print("STATS", client.get("/api/knowledge/stats").json())
    print("PROJECTS", client.get("/api/projects").json())

    results = [
        run_case(
            client,
            "A3",
            "公司是否做过 IL23R 的体内验证？",
            "IBD-TX-07",
        ),
        run_case(
            client,
            "A1",
            "IL23R 在 IBD 的 CD4+ 记忆 T 细胞中是否有选择性表达？公司做过哪些验证？",
            "IBD-TX-07",
        ),
        run_case(
            client,
            "ACL",
            "ONCO-02 项目里 IL23R 在肿瘤浸润淋巴细胞中的结果是什么？",
            "IBD-TX-07",
        ),
    ]
    Path("data/eval/api_smoke_result.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

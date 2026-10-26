"""运行一个研究任务（P4 CLI）。

示例：
    uv run python scripts/run_task.py "公司是否做过 IL23R 的体内验证？"
    uv run python scripts/run_task.py "ONCO-02 项目里 IL23R 的结果？" --user scientist_031 --project IBD-TX-07
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.utils.console import configure_console  # noqa: E402

configure_console()

from app.config import get_settings  # noqa: E402
from app.graph.builder import run_research  # noqa: E402
from app.graph.services import build_services  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="运行医药研发研究任务")
    parser.add_argument("question", help="研究问题")
    parser.add_argument("--user", default="scientist_031", help="演示用户")
    parser.add_argument("--project", default="IBD-TX-07", help="项目空间")
    parser.add_argument("--task-id", default=None)
    parser.add_argument("--show-events", action="store_true")
    parser.add_argument("--json", action="store_true", help="输出 JSON 摘要")
    args = parser.parse_args()

    settings = get_settings()
    services = build_services(settings)
    try:
        result = run_research(
            services,
            args.question,
            user_id=args.user,
            project_id=args.project,
            task_id=args.task_id,
        )
    finally:
        services.close()

    final_evidence = result.get("final_evidence")
    if final_evidence is None:
        final_evidence = result.get("evidence", [])

    if args.json:
        print(
            json.dumps(
                {
                    "task_id": result.get("task_id"),
                    "status": result.get("status"),
                    "entities": [
                        entity.model_dump(mode="json")
                        for entity in result.get("entities", [])
                    ],
                    "subquestions": [
                        item.model_dump(mode="json")
                        for item in result.get("subquestions", [])
                    ],
                    "final_evidence": [
                        item.model_dump(mode="json")
                        for item in final_evidence
                    ],
                    "errors": [
                        item.model_dump(mode="json")
                        for item in result.get("errors", [])
                    ],
                    "events": [
                        item.model_dump(mode="json")
                        for item in result.get("events", [])
                    ],
                    "report_md": result.get("report_md"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(f"\nTASK {result.get('task_id')} | status={result.get('status')}")
    print(f"QUESTION: {result.get('question')}")
    print(
        "ENTITIES: "
        + ", ".join(
            entity.name for entity in result.get("entities", [])
        )
    )
    print("\nSUBQUESTIONS")
    for item in result.get("subquestions", []):
        print(
            f"  {item.id} [{item.intent}] "
            f"{', '.join(source.value for source in item.sources)}"
        )
    print("\nEVIDENCE")
    for index, item in enumerate(final_evidence[:10], start=1):
        print(
            f"  {index}. [{item.source_type.value}] {item.source_id} "
            f"| {item.locator.section or ''}"
        )
        print(f"     {item.quote[:160]}")
    if result.get("errors"):
        print("\nERRORS")
        for item in result["errors"]:
            print(f"  - {item.node}: {item.error_type}: {item.message}")
    if args.show_events:
        print("\nEVENTS")
        for event in result.get("events", []):
            print(
                f"  {event.timestamp.isoformat()} [{event.event_type}] "
                f"{event.node}: {event.message}"
            )
    print("\nREPORT\n")
    print(result.get("report_md", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

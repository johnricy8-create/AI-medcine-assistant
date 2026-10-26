"""LangGraph 主图组装。"""

from __future__ import annotations

import uuid
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    fan_out,
    finalize_node,
    intake_node,
    link_entities_node,
    normalize_node,
    plan_node,
    retrieve_source_node,
)
from app.graph.services import GraphServices
from app.graph.state import ResearchState
from app.schemas import TaskStatus


def route_after_intake(state: ResearchState) -> str:
    if state.get("status") == TaskStatus.BLOCKED.value:
        return "finalize"
    return "link_entities"


def build_graph(
    services: GraphServices,
    *,
    checkpointer: Any | None = None,
):
    graph = StateGraph(ResearchState)
    graph.add_node("intake", lambda state: intake_node(state, services))
    graph.add_node("link_entities", lambda state: link_entities_node(state, services))
    graph.add_node("plan", lambda state: plan_node(state, services))
    graph.add_node(
        "retrieve_source",
        lambda payload: retrieve_source_node(payload, services),
    )
    graph.add_node("normalize", lambda state: normalize_node(state, services))
    graph.add_node("finalize", lambda state: finalize_node(state, services))

    graph.add_edge(START, "intake")
    graph.add_conditional_edges("intake", route_after_intake)
    graph.add_edge("link_entities", "plan")
    graph.add_conditional_edges("plan", fan_out)
    graph.add_edge("retrieve_source", "normalize")
    graph.add_edge("normalize", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer or InMemorySaver())


def run_research(
    services: GraphServices,
    question: str,
    *,
    user_id: str,
    project_id: str,
    task_id: str | None = None,
    trace_id: str | None = None,
    checkpointer: Any | None = None,
) -> dict[str, Any]:
    task_id = task_id or f"rt-{uuid.uuid4().hex[:10]}"
    trace_id = trace_id or f"rr-{uuid.uuid4().hex[:10]}"
    compiled = build_graph(services, checkpointer=checkpointer)
    return compiled.invoke(
        {
            "task_id": task_id,
            "trace_id": trace_id,
            "user_id": user_id,
            "project_id": project_id,
            "question": question,
        },
        config={"configurable": {"thread_id": task_id}},
    )

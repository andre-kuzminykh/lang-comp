#!/usr/bin/env python3
"""
Runner for graph.json — TV Graphics Production workflow.

Registers stub handlers so the graph can be executed locally
without real external services. Replace stubs with real
implementations when integrating with production systems.
"""

import json
import sys
from langgraph.types import Command
from comp import GraphSpecCompiler, LocalRegistry, load_spec


# ── LLM runner (stub) ──────────────────────────────────────────

def stub_llm_runner(config, inputs):
    """Simulates LLM response based on node config."""
    request = inputs.get("request", {})
    text = request.get("text", "") if isinstance(request, dict) else str(request)
    return {
        "normalized_brief": {"text": text, "source": "ai_stub"},
        "missing_fields": [],
        "recommended_type": "collage",
        "recommended_urgency": "normal",
        "confidence": 0.92,
    }


# ── Function handlers ──────────────────────────────────────────

def brief_validate(inputs):
    """Validates brief completeness."""
    brief = inputs.get("brief", {})
    missing = brief.get("missing_fields", []) if brief else []
    return {"is_complete": len(missing) == 0, "missing": missing}


def routing_classify_and_route(inputs):
    """Classifies request type and urgency."""
    brief = inputs.get("brief", {}) or {}
    return {
        "type": brief.get("recommended_type", "collage"),
        "urgency": brief.get("recommended_urgency", "normal"),
        "assigned_team": "design",
    }


def priority_check_conflict(inputs):
    """Checks for priority conflicts (stub: no conflicts)."""
    return {"has_conflict": False}


def routing_assign_executor(inputs):
    """Assigns executor based on classification."""
    classification = inputs.get("classification", {}) or {}
    return {
        "executor": "designer_01",
        "type": classification.get("type", "collage"),
    }


# ── Tool runners ───────────────────────────────────────────────

def stub_tool(tool_spec, inputs):
    """Generic stub for all unresolved tools."""
    tool_id = tool_spec.get("id", "unknown")
    return {"ok": True, "tool": tool_id, "echo": inputs, "id": "stub_001"}


# ── Build registry ─────────────────────────────────────────────

def make_registry():
    registry = LocalRegistry()

    # LLM runner
    registry.register_llm_runner("stub_llm", stub_llm_runner)

    # Function handlers
    registry.register_function("brief.validate", brief_validate)
    registry.register_function("routing.classify_and_route", routing_classify_and_route)
    registry.register_function("priority.check_conflict", priority_check_conflict)
    registry.register_function("routing.assign_executor", routing_assign_executor)

    # Tool runners (all unresolved tools use the same stub)
    for tool_id in [
        "workflow.create_request",
        "workflow.send_clarification",
        "ai.generate_draft",
        "design.finalize_asset",
        "design.apply_revisions",
        "broadcast.deploy_rt",
        "storage.publish_asset",
        "editing.send_links",
        "workflow.close_request",
    ]:
        registry.register_tool(tool_id, stub_tool)

    return registry


# ── Auto-approve interrupts ────────────────────────────────────

AUTO_APPROVALS = {
    "resolve_priority_conflict": {"status": "approved", "priority": "confirmed"},
    "editorial_review": {"status": "approved", "comments": []},
}


# ── Main ───────────────────────────────────────────────────────

def main():
    spec_path = sys.argv[1] if len(sys.argv) > 1 else "graph.json"
    input_text = sys.argv[2] if len(sys.argv) > 2 else "Сделать плашку для новостного выпуска"

    spec = load_spec(spec_path)
    registry = make_registry()
    compiler = GraphSpecCompiler(registry, default_llm_runner="stub_llm")
    graph = compiler.compile_spec(spec)

    payload = {"input": {"text": input_text}}
    config = {"configurable": {"thread_id": "local-1"}}

    print(f"Running graph: {spec['graph_id']}")
    print(f"Input: {input_text}\n")

    # First invocation
    result = graph.invoke(payload, config=config)

    # Handle interrupts (approval nodes) automatically
    max_iterations = 10
    iteration = 0
    while iteration < max_iterations:
        state = graph.get_state(config)
        if not state.tasks or not any(t.interrupts for t in state.tasks):
            break

        for task in state.tasks:
            if task.interrupts:
                node_id = task.name
                interrupt_data = task.interrupts[0].value
                print(f"[Auto-approve] Node: {node_id}")
                print(f"  Message: {interrupt_data.get('message', 'N/A')}")

                approval = AUTO_APPROVALS.get(node_id, {"status": "approved"})
                result = graph.invoke(
                    Command(resume=approval),
                    config=config,
                )
        iteration += 1

    print("\n── Result ──")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

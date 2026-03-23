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
    """Simulates LLM response based on output_schema."""
    schema = config.get("output_schema", {})
    props = schema.get("properties", {})
    result = {}
    for key, prop in props.items():
        t = prop.get("type", "string")
        # Handle union types like ["string", "null"]
        if isinstance(t, list):
            t = t[0]
        if t == "object":
            result[key] = {"stub": True}
        elif t == "array":
            result[key] = []
        elif t == "number":
            result[key] = 0.92
        elif t == "integer":
            result[key] = 0
        elif t == "boolean":
            result[key] = True
        else:
            result[key] = f"stub_{key}"
    return result or {"stub": True}


# ── Retrieval runner (stub) ───────────────────────────────────

def stub_retrieval_runner(config, inputs):
    """Simulates design context retrieval."""
    return {
        "documents": [
            {
                "source": config.get("source", "design_guidelines"),
                "score": 0.9,
                "text": "Stub design guideline: brand colors, 1920x1080, safe zone margins.",
            }
        ]
    }


# ── Function handlers ──────────────────────────────────────────

def workflow_validate_brief(inputs):
    """Validates brief completeness."""
    return {"status": "complete", "missing_fields": [], "blocking_reason": None}


def workflow_mark_invalid_request(inputs):
    """Marks request as invalid."""
    return {"status": "invalid", "reason": "Request could not be validated"}


def workflow_check_priority_conflict(inputs):
    """Checks for priority conflicts."""
    return {"conflict": False}


def workflow_quality_gate(inputs):
    """Pre-review quality gate — passes through."""
    return inputs.get("result", {}) or {}


def workflow_evaluate_review_outcome(inputs):
    """Captures editorial review outcome."""
    approval = inputs.get("approval", {}) or {}
    iteration_count = inputs.get("iteration_count") or 0
    status = approval.get("status", "approved")
    return {
        "status": status,
        "comments": approval.get("comments", ""),
        "iteration_count": iteration_count + 1,
        "max_iterations_reached": iteration_count + 1 >= 5,
    }


def workflow_close_request(inputs):
    """Closes the request."""
    return {
        "closed": True,
        "final_status": inputs.get("approval_status", {}).get("status", "completed"),
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

    # Retrieval runner
    registry.register_retrieval("stub_retrieval", stub_retrieval_runner)

    # Function handlers
    registry.register_function("workflow.validate_brief", workflow_validate_brief)
    registry.register_function("workflow.mark_invalid_request", workflow_mark_invalid_request)
    registry.register_function("workflow.check_priority_conflict", workflow_check_priority_conflict)
    registry.register_function("workflow.quality_gate", workflow_quality_gate)
    registry.register_function("workflow.evaluate_review_outcome", workflow_evaluate_review_outcome)
    registry.register_function("workflow.close_request", workflow_close_request)

    # Tool runners (all unresolved tools use the same stub)
    for tool_id in [
        "workflow.create_request",
        "workflow.send_clarification",
        "workflow.assign_rt",
        "workflow.assign_collage",
        "workflow.assign_motion",
        "vizrt.create_rt_draft",
        "storage.create_collage_draft",
        "storage.create_motion_draft",
        "cosmedia.deploy_rt",
        "storage.publish_collage_final",
        "storage.publish_motion_final",
        "workflow.deliver_to_nle",
    ]:
        registry.register_tool(tool_id, stub_tool)

    return registry


# ── Auto-approve interrupts ────────────────────────────────────

DEFAULT_ROUTE = "collage"

AUTO_APPROVALS = {
    "supervisor_triage": {"route": DEFAULT_ROUTE, "urgency": "normal", "deadline": "2h"},
    "wait_for_clarification": {"text": "clarified data", "source": "stub"},
    "hd_priority_resolution": {"route": DEFAULT_ROUTE, "urgency": "confirmed", "status": "approved"},
    "rt_finalize": {"status": "approved", "comments": []},
    "collage_finalize": {"status": "approved", "comments": []},
    "motion_finalize": {"status": "approved", "comments": []},
    "rt_editor_review": {"status": "approved", "comments": []},
    "collage_editor_review": {"status": "approved", "comments": []},
    "motion_editor_review": {"status": "approved", "comments": []},
    "rt_rework": {"status": "approved", "asset": {"reworked": True}},
    "collage_rework": {"status": "approved", "asset": {"reworked": True}},
    "motion_rework": {"status": "approved", "asset": {"reworked": True}},
}


# ── Main ───────────────────────────────────────────────────────

def main():
    spec_path = sys.argv[1] if len(sys.argv) > 1 else "graph.json"
    input_text = sys.argv[2] if len(sys.argv) > 2 else "Сделать плашку для новостного выпуска"
    route = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_ROUTE

    # Update route-dependent approvals
    AUTO_APPROVALS["supervisor_triage"]["route"] = route
    AUTO_APPROVALS["hd_priority_resolution"]["route"] = route

    spec = load_spec(spec_path)
    registry = make_registry()
    compiler = GraphSpecCompiler(
        registry,
        default_llm_runner="stub_llm",
        default_retrieval_runner="stub_retrieval",
    )
    graph = compiler.compile_spec(spec)

    payload = {"input": {"text": input_text}}
    config = {"configurable": {"thread_id": "local-1"}}

    print(f"Running graph: {spec['graph_id']}")
    print(f"Input: {input_text}")
    print(f"Route: {route}\n")

    # First invocation
    result = graph.invoke(payload, config=config)

    # Handle interrupts (approval nodes) automatically
    max_iterations = 20
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

#!/usr/bin/env python3
"""
Minimal Graph Spec v0.1 -> LangGraph compiler.

Supported node kinds:
- function
- llm
- tool
- retrieval
- approval

Supported edge kinds:
- direct
- conditional

Design goals:
- minimal but extensible
- source-of-truth is Graph Spec JSON
- compiler builds a runnable LangGraph graph object
- external integrations are delegated to registries / adapters

Usage:
    from langgraph_spec_compiler import GraphSpecCompiler, LocalRegistry, load_spec
    spec = load_spec("example_graph_spec.json")
    registry = LocalRegistry()
    graph = GraphSpecCompiler(registry).compile_spec(spec)
    result = graph.invoke({"input": {"text": "hello"}}, config={"configurable": {"thread_id": "t-1"}})

CLI:
    python langgraph_spec_compiler.py --spec example_graph_spec.json --print-mermaid
"""

from __future__ import annotations

import argparse
import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
from typing_extensions import TypedDict

try:
    from langgraph.graph import StateGraph, START, END
    from langgraph.types import interrupt
except Exception as e:  # pragma: no cover
    StateGraph = None
    START = "__START__"
    END = "__END__"
    interrupt = None
    _IMPORT_ERROR = e
else:
    _IMPORT_ERROR = None

try:
    from langgraph.checkpoint.memory import InMemorySaver
except Exception:  # pragma: no cover
    InMemorySaver = None


# ---------------------------
# Exceptions
# ---------------------------

class GraphSpecError(Exception):
    """Raised when the Graph Spec is invalid."""


class RegistryError(Exception):
    """Raised when a handler/tool cannot be resolved."""


# ---------------------------
# Registry
# ---------------------------

FunctionHandler = Callable[[Dict[str, Any]], Dict[str, Any]]
LLMRunner = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
ToolRunner = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
RetrievalRunner = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]


@dataclass
class LocalRegistry:
    """
    Minimal runtime registry.

    You can register callables directly, or rely on dotted-path imports
    for function handlers via config.handler.
    """
    functions: Dict[str, FunctionHandler] = field(default_factory=dict)
    llm_runners: Dict[str, LLMRunner] = field(default_factory=dict)
    tools: Dict[str, ToolRunner] = field(default_factory=dict)
    retrievals: Dict[str, RetrievalRunner] = field(default_factory=dict)

    def register_function(self, name: str, fn: FunctionHandler) -> None:
        self.functions[name] = fn

    def register_llm_runner(self, name: str, fn: LLMRunner) -> None:
        self.llm_runners[name] = fn

    def register_tool(self, name: str, fn: ToolRunner) -> None:
        self.tools[name] = fn

    def register_retrieval(self, name: str, fn: RetrievalRunner) -> None:
        self.retrievals[name] = fn

    def get_function(self, name: str) -> FunctionHandler:
        if name in self.functions:
            return self.functions[name]
        return import_dotted_callable(name)

    def get_llm_runner(self, name: str) -> LLMRunner:
        if name in self.llm_runners:
            return self.llm_runners[name]
        return import_dotted_callable(name)

    def get_tool(self, name: str) -> ToolRunner:
        if name in self.tools:
            return self.tools[name]
        return import_dotted_callable(name)

    def get_retrieval(self, name: str) -> RetrievalRunner:
        if name in self.retrievals:
            return self.retrievals[name]
        return import_dotted_callable(name)


def import_dotted_callable(path: str) -> Callable[..., Any]:
    if "." not in path:
        raise RegistryError(f"Expected dotted path, got: {path!r}")
    module_name, attr_name = path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    try:
        fn = getattr(module, attr_name)
    except AttributeError as e:
        raise RegistryError(f"Callable not found: {path}") from e
    if not callable(fn):
        raise RegistryError(f"Resolved object is not callable: {path}")
    return fn


# ---------------------------
# Spec loading / validation
# ---------------------------

SUPPORTED_NODE_KINDS = {"function", "llm", "tool", "retrieval", "approval"}
SUPPORTED_EDGE_TYPES = {"direct", "conditional"}
SUPPORTED_TOOL_KINDS = {"mcp", "api", "local", "unresolved"}


def load_spec(path: str | Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_spec(spec: Dict[str, Any]) -> None:
    required_top_level = {"graph_id", "state_schema", "tools", "nodes", "edges", "execution"}
    missing = required_top_level - set(spec.keys())
    if missing:
        raise GraphSpecError(f"Missing required top-level keys: {sorted(missing)}")

    if not isinstance(spec["graph_id"], str) or not spec["graph_id"]:
        raise GraphSpecError("graph_id must be a non-empty string")

    if not isinstance(spec["state_schema"], dict):
        raise GraphSpecError("state_schema must be an object")

    if not isinstance(spec["tools"], list):
        raise GraphSpecError("tools must be an array")

    if not isinstance(spec["nodes"], list) or not spec["nodes"]:
        raise GraphSpecError("nodes must be a non-empty array")

    if not isinstance(spec["edges"], list) or not spec["edges"]:
        raise GraphSpecError("edges must be a non-empty array")

    tool_ids = set()
    for tool in spec["tools"]:
        if "id" not in tool:
            raise GraphSpecError("Every tool must have an id")
        if tool["id"] in tool_ids:
            raise GraphSpecError(f"Duplicate tool id: {tool['id']}")
        tool_ids.add(tool["id"])
        kind = tool.get("kind")
        if kind not in SUPPORTED_TOOL_KINDS:
            raise GraphSpecError(f"Unsupported tool kind {kind!r} for tool {tool['id']}")
        if "transport" not in tool or not isinstance(tool["transport"], dict):
            raise GraphSpecError(f"Tool {tool['id']} must define transport")

    node_ids = set()
    for node in spec["nodes"]:
        for key in ("id", "kind", "inputs", "outputs", "config"):
            if key not in node:
                raise GraphSpecError(f"Node missing required key {key!r}: {node}")
        if node["id"] in node_ids:
            raise GraphSpecError(f"Duplicate node id: {node['id']}")
        node_ids.add(node["id"])

        if node["kind"] not in SUPPORTED_NODE_KINDS:
            raise GraphSpecError(f"Unsupported node kind {node['kind']!r} for node {node['id']}")

        if not isinstance(node["inputs"], dict) or not isinstance(node["outputs"], dict):
            raise GraphSpecError(f"Node {node['id']} inputs/outputs must be objects")

        if node["kind"] == "function":
            handler = node["config"].get("handler")
            if not isinstance(handler, str) or not handler:
                raise GraphSpecError(f"Function node {node['id']} must define config.handler")

        if node["kind"] == "llm":
            # keep v0.1 strict: output_schema required for structured output
            if "output_schema" not in node["config"]:
                raise GraphSpecError(f"LLM node {node['id']} must define config.output_schema")

        if node["kind"] == "tool":
            tool_ref = node.get("tool_ref")
            if not isinstance(tool_ref, str) or not tool_ref:
                raise GraphSpecError(f"Tool node {node['id']} must define tool_ref")
            if tool_ref not in tool_ids:
                raise GraphSpecError(f"Tool node {node['id']} references unknown tool_ref {tool_ref!r}")

    for edge in spec["edges"]:
        edge_type = edge.get("type")
        if edge_type not in SUPPORTED_EDGE_TYPES:
            raise GraphSpecError(f"Unsupported edge type: {edge_type!r}")

        if edge_type == "direct":
            if "from" not in edge or "to" not in edge:
                raise GraphSpecError(f"Direct edge must include from and to: {edge}")
            if edge["from"] != "START" and edge["from"] not in node_ids:
                raise GraphSpecError(f"Direct edge references unknown source node: {edge['from']}")
            if edge["to"] != "END" and edge["to"] not in node_ids:
                raise GraphSpecError(f"Direct edge references unknown target node: {edge['to']}")

        elif edge_type == "conditional":
            if "from" not in edge or "conditions" not in edge:
                raise GraphSpecError(f"Conditional edge must include from and conditions: {edge}")
            if edge["from"] != "START" and edge["from"] not in node_ids:
                raise GraphSpecError(f"Conditional edge references unknown source node: {edge['from']}")
            if not isinstance(edge["conditions"], list) or not edge["conditions"]:
                raise GraphSpecError(f"Conditional edge must define non-empty conditions: {edge}")
            for cond in edge["conditions"]:
                if "when" not in cond or "to" not in cond:
                    raise GraphSpecError(f"Conditional branch must include when and to: {cond}")
                if cond["to"] != "END" and cond["to"] not in node_ids:
                    raise GraphSpecError(f"Conditional edge references unknown target node: {cond['to']}")

    # simple orphan check (except START/END)
    inbound = {nid: 0 for nid in node_ids}
    outbound = {nid: 0 for nid in node_ids}

    for edge in spec["edges"]:
        if edge["type"] == "direct":
            if edge["from"] != "START":
                outbound[edge["from"]] += 1
            if edge["to"] != "END":
                inbound[edge["to"]] += 1
        else:
            if edge["from"] != "START":
                outbound[edge["from"]] += len(edge["conditions"])
            for cond in edge["conditions"]:
                if cond["to"] != "END":
                    inbound[cond["to"]] += 1

    orphans = [nid for nid in node_ids if inbound[nid] == 0 and not _is_entrypoint(nid, spec)]
    if orphans:
        raise GraphSpecError(f"Orphaned nodes detected (no inbound edge): {orphans}")


def _is_entrypoint(node_id: str, spec: Dict[str, Any]) -> bool:
    for edge in spec["edges"]:
        if edge.get("from") == "START":
            if edge["type"] == "direct" and edge.get("to") == node_id:
                return True
            if edge["type"] == "conditional":
                for cond in edge["conditions"]:
                    if cond.get("to") == node_id:
                        return True
    return False


# ---------------------------
# Path resolution
# ---------------------------

def deep_get(data: Mapping[str, Any], path: str, default: Any = None) -> Any:
    current: Any = data
    for part in path.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                return default
            current = current[part]
        elif isinstance(current, list):
            try:
                idx = int(part)
                current = current[idx]
            except (ValueError, IndexError):
                return default
        else:
            return default
    return current


def resolve_value(expr: Any, state: Dict[str, Any], result: Optional[Dict[str, Any]] = None) -> Any:
    if isinstance(expr, str):
        if expr == "$result":
            if result is None:
                raise ValueError("$result used before result exists")
            return result
        if expr.startswith("$state."):
            return deep_get(state, expr[len("$state."):])
        if expr.startswith("$result."):
            if result is None:
                raise ValueError("$result.* used before result exists")
            return deep_get(result, expr[len("$result."):])
        return expr
    if isinstance(expr, list):
        return [resolve_value(v, state, result=result) for v in expr]
    if isinstance(expr, dict):
        return {k: resolve_value(v, state, result=result) for k, v in expr.items()}
    return expr


def resolve_inputs(input_map: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    return {k: resolve_value(v, state) for k, v in input_map.items()}


def apply_outputs(output_map: Dict[str, Any], result: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}
    for state_key, expr in output_map.items():
        updates[state_key] = resolve_value(expr, state, result=result)
    return updates


# ---------------------------
# JSONLogic-lite
# ---------------------------

def resolve_logic_value(expr: Any, state: Dict[str, Any]) -> Any:
    if isinstance(expr, dict) and "var" in expr:
        return deep_get(state, expr["var"])
    return expr


def eval_logic(expr: Any, state: Dict[str, Any]) -> bool:
    if expr is True:
        return True
    if expr is False:
        return False

    if isinstance(expr, dict):
        if "==" in expr:
            a, b = expr["=="]
            return resolve_logic_value(a, state) == resolve_logic_value(b, state)
        if "!=" in expr:
            a, b = expr["!="]
            return resolve_logic_value(a, state) != resolve_logic_value(b, state)
        if ">=" in expr:
            a, b = expr[">="]
            return resolve_logic_value(a, state) >= resolve_logic_value(b, state)
        if "<=" in expr:
            a, b = expr["<="]
            return resolve_logic_value(a, state) <= resolve_logic_value(b, state)
        if ">" in expr:
            a, b = expr[">"]
            return resolve_logic_value(a, state) > resolve_logic_value(b, state)
        if "<" in expr:
            a, b = expr["<"]
            return resolve_logic_value(a, state) < resolve_logic_value(b, state)
        if "and" in expr:
            return all(eval_logic(x, state) for x in expr["and"])
        if "or" in expr:
            return any(eval_logic(x, state) for x in expr["or"])
        if "not" in expr:
            return not eval_logic(expr["not"], state)

    raise GraphSpecError(f"Unsupported conditional expression: {expr!r}")


# ---------------------------
# Compiler
# ---------------------------

class GraphSpecCompiler:
    def __init__(
        self,
        registry: Optional[LocalRegistry] = None,
        default_llm_runner: Optional[str] = None,
    ) -> None:
        self.registry = registry or LocalRegistry()
        self.default_llm_runner = default_llm_runner

    def compile_spec(self, spec: Dict[str, Any], *, checkpointer: Any = None):
        if _IMPORT_ERROR is not None:
            raise RuntimeError(
                "langgraph is not importable in this environment. "
                f"Original error: {_IMPORT_ERROR}"
            )

        validate_spec(spec)
        state_cls = self._build_state_schema(spec["state_schema"])
        builder = StateGraph(state_cls)

        tool_index = {tool["id"]: tool for tool in spec["tools"]}

        for node_spec in spec["nodes"]:
            node_fn = self._build_node(node_spec, tool_index)
            builder.add_node(node_spec["id"], node_fn)

        self._add_edges(builder, spec["edges"])

        execution = spec.get("execution", {}) or {}
        requires_checkpointer = bool(execution.get("requires_checkpointer", False))

        if checkpointer is None and requires_checkpointer and InMemorySaver is not None:
            checkpointer = InMemorySaver()

        return builder.compile(checkpointer=checkpointer)

    def _build_state_schema(self, state_schema: Dict[str, Any]):
        fields: Dict[str, Any] = {}
        for key, type_name in state_schema.items():
            # v0.1 keeps state typing intentionally minimal.
            fields[key] = Any
        return TypedDict("GraphState", fields, total=False)

    def _build_node(self, node_spec: Dict[str, Any], tool_index: Dict[str, Dict[str, Any]]) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
        kind = node_spec["kind"]

        if kind == "function":
            handler_name = node_spec["config"]["handler"]
            handler = self.registry.get_function(handler_name)

            def node(state: Dict[str, Any]) -> Dict[str, Any]:
                inputs = resolve_inputs(node_spec["inputs"], state)
                result = handler(inputs)
                if not isinstance(result, dict):
                    raise GraphSpecError(f"Function handler {handler_name} must return dict, got {type(result).__name__}")
                return apply_outputs(node_spec["outputs"], result, state)

            return node

        if kind == "llm":
            runner_name = node_spec["config"].get("runner") or self.default_llm_runner
            if not runner_name:
                raise RegistryError(
                    f"LLM node {node_spec['id']} has no config.runner and no default_llm_runner was provided"
                )
            llm_runner = self.registry.get_llm_runner(runner_name)

            def node(state: Dict[str, Any]) -> Dict[str, Any]:
                inputs = resolve_inputs(node_spec["inputs"], state)
                result = llm_runner(node_spec["config"], inputs)
                if not isinstance(result, dict):
                    raise GraphSpecError(f"LLM runner {runner_name} must return dict, got {type(result).__name__}")
                return apply_outputs(node_spec["outputs"], result, state)

            return node

        if kind == "tool":
            tool_ref = node_spec["tool_ref"]
            tool_spec = tool_index[tool_ref]
            tool_runner = self._resolve_tool_runner(tool_ref, tool_spec)

            def node(state: Dict[str, Any]) -> Dict[str, Any]:
                inputs = resolve_inputs(node_spec["inputs"], state)
                result = tool_runner(tool_spec, inputs)
                if not isinstance(result, dict):
                    raise GraphSpecError(f"Tool runner for {tool_ref} must return dict, got {type(result).__name__}")
                return apply_outputs(node_spec["outputs"], result, state)

            return node

        if kind == "retrieval":
            retrieval_name = node_spec["config"].get("runner")
            if not retrieval_name:
                raise RegistryError(f"Retrieval node {node_spec['id']} must define config.runner")
            retrieval_runner = self.registry.get_retrieval(retrieval_name)

            def node(state: Dict[str, Any]) -> Dict[str, Any]:
                inputs = resolve_inputs(node_spec["inputs"], state)
                result = retrieval_runner(node_spec["config"], inputs)
                if not isinstance(result, dict):
                    raise GraphSpecError(f"Retrieval runner {retrieval_name} must return dict, got {type(result).__name__}")
                return apply_outputs(node_spec["outputs"], result, state)

            return node

        if kind == "approval":
            def node(state: Dict[str, Any]) -> Dict[str, Any]:
                if interrupt is None:
                    raise RuntimeError("langgraph.types.interrupt is not available in this environment")
                payload = {
                    "message": node_spec["config"].get("message_template", "Approval required"),
                    "inputs": resolve_inputs(node_spec["inputs"], state),
                    "node_id": node_spec["id"],
                }
                result = interrupt(payload)
                if not isinstance(result, dict):
                    # allow scalar approval results by wrapping them
                    result = {"value": result}
                return apply_outputs(node_spec["outputs"], result, state)

            return node

        raise GraphSpecError(f"Unsupported node kind: {kind}")

    def _resolve_tool_runner(self, tool_ref: str, tool_spec: Dict[str, Any]) -> ToolRunner:
        # Explicit local registration takes precedence.
        if tool_ref in self.registry.tools:
            fn = self.registry.get_tool(tool_ref)
            return lambda _tool_spec, inputs: fn(_tool_spec, inputs)

        kind = tool_spec.get("kind")
        transport = tool_spec.get("transport", {}) or {}

        # For local tools, allow a dotted path in transport.handler.
        if kind == "local":
            handler = transport.get("handler")
            if not handler:
                raise RegistryError(f"Local tool {tool_ref} must define transport.handler")
            fn = import_dotted_callable(handler)
            return lambda _tool_spec, inputs: fn(_tool_spec, inputs)

        # For unresolved/mcp/api tools, require explicit adapter registration.
        def not_implemented(_tool_spec: Dict[str, Any], _inputs: Dict[str, Any]) -> Dict[str, Any]:
            raise NotImplementedError(
                f"No runtime adapter registered for tool {tool_ref} (kind={kind}, transport={transport})"
            )

        return not_implemented

    def _add_edges(self, builder: Any, edges: List[Dict[str, Any]]) -> None:
        for edge in edges:
            if edge["type"] == "direct":
                src = START if edge["from"] == "START" else edge["from"]
                dst = END if edge["to"] == "END" else edge["to"]
                builder.add_edge(src, dst)

            elif edge["type"] == "conditional":
                src = START if edge["from"] == "START" else edge["from"]
                conditions = edge["conditions"]

                route_map: Dict[str, Any] = {}
                for idx, cond in enumerate(conditions):
                    route_name = f"route_{idx}"
                    route_map[route_name] = END if cond["to"] == "END" else cond["to"]

                def router(state: Dict[str, Any], _conditions=conditions):
                    for idx, cond in enumerate(_conditions):
                        if eval_logic(cond["when"], state):
                            return f"route_{idx}"
                    raise GraphSpecError(f"No conditional branch matched for edge from {edge['from']}")

                builder.add_conditional_edges(src, router, route_map)

            else:
                raise GraphSpecError(f"Unsupported edge type: {edge['type']}")


# ---------------------------
# Example runtime functions
# ---------------------------

def example_llm_runner(config: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Placeholder structured-output LLM runner.

    Replace this with a real provider call.
    """
    text = inputs.get("text") or inputs.get("raw_text") or json.dumps(inputs, ensure_ascii=False)
    if "task" in text.lower():
        return {
            "intent": "create_task",
            "confidence": 0.91,
            "title": "Auto-created task",
            "extracted_fields": {
                "title": "Auto-created task"
            }
        }
    return {
        "intent": "review",
        "confidence": 0.52,
        "title": None,
        "extracted_fields": {}
    }


def example_local_tool(_tool_spec: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, "echo": inputs, "id": "local_123"}


def example_retrieval_runner(config: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "documents": [
            {
                "source": config.get("source", "kb"),
                "score": 0.9,
                "text": f"Relevant doc for query: {inputs.get('query')}"
            }
        ]
    }


# ---------------------------
# Sample function handlers
# ---------------------------

def sample_normalize_input(inputs: Dict[str, Any]) -> Dict[str, Any]:
    raw = inputs.get("raw", {})
    if isinstance(raw, dict):
        return raw
    return {"text": str(raw)}


def sample_policy_decide(inputs: Dict[str, Any]) -> Dict[str, Any]:
    classification = inputs["classification"]
    confidence = classification.get("confidence", 0)
    if confidence >= 0.85 and classification.get("intent") == "create_task":
        return {"route": "tool"}
    return {"route": "review"}


# ---------------------------
# CLI
# ---------------------------

EXAMPLE_SPEC = {
    "graph_id": "request_flow_v1",
    "state_schema": {
        "input": "object",
        "classification": "object",
        "result": "object",
        "approval": "object",
        "error": "object"
    },
    "tools": [
        {
            "id": "tasks.create_task",
            "kind": "local",
            "description": "Create task locally",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "transport": {
                "handler": "langgraph_spec_compiler.example_local_tool",
                "server": None,
                "tool_name": None
            }
        }
    ],
    "nodes": [
        {
            "id": "normalize_input",
            "kind": "function",
            "inputs": {"raw": "$state.input"},
            "outputs": {"input": "$result"},
            "config": {"handler": "langgraph_spec_compiler.sample_normalize_input"},
            "tool_ref": None
        },
        {
            "id": "classify",
            "kind": "llm",
            "inputs": {"text": "$state.input.text"},
            "outputs": {"classification": "$result"},
            "config": {
                "runner": "langgraph_spec_compiler.example_llm_runner",
                "model": "gpt-4.1",
                "system_prompt": "Return JSON",
                "prompt_template": "Text: {{text}}",
                "output_schema": {"type": "object"}
            },
            "tool_ref": None
        },
        {
            "id": "policy_gate",
            "kind": "function",
            "inputs": {"classification": "$state.classification"},
            "outputs": {"result": "$result"},
            "config": {"handler": "langgraph_spec_compiler.sample_policy_decide"},
            "tool_ref": None
        },
        {
            "id": "create_task",
            "kind": "tool",
            "inputs": {"title": "$state.classification.extracted_fields.title"},
            "outputs": {"result": "$result"},
            "config": {},
            "tool_ref": "tasks.create_task"
        },
        {
            "id": "human_review",
            "kind": "approval",
            "inputs": {"classification": "$state.classification"},
            "outputs": {"approval": "$result"},
            "config": {"message_template": "Review and approve"},
            "tool_ref": None
        }
    ],
    "edges": [
        {"from": "START", "to": "normalize_input", "type": "direct"},
        {"from": "normalize_input", "to": "classify", "type": "direct"},
        {"from": "classify", "to": "policy_gate", "type": "direct"},
        {
            "from": "policy_gate",
            "type": "conditional",
            "conditions": [
                {
                    "when": {"==": [{"var": "result.route"}, "tool"]},
                    "to": "create_task"
                },
                {
                    "when": True,
                    "to": "human_review"
                }
            ]
        },
        {"from": "create_task", "to": "END", "type": "direct"},
        {"from": "human_review", "to": "END", "type": "direct"}
    ],
    "execution": {
        "requires_checkpointer": True
    }
}


def _auto_registry_from_spec(spec: Dict[str, Any]) -> tuple:
    """
    Scan a graph spec and auto-register stub handlers for every node.
    Returns (registry, default_llm_runner_name).
    """
    registry = LocalRegistry()

    # Generic stubs
    def _stub_llm(config: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        schema = config.get("output_schema", {})
        props = schema.get("properties", {})
        result: Dict[str, Any] = {}
        for key, prop in props.items():
            t = prop.get("type", "string")
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

    def _stub_tool(_tool_spec: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True, "tool": _tool_spec.get("id", "unknown"), "echo": inputs, "id": "auto_001"}

    def _stub_function(inputs: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in inputs.items()}

    llm_runner_name = "auto_llm_runner"
    registry.register_llm_runner(llm_runner_name, _stub_llm)

    for node in spec.get("nodes", []):
        kind = node["kind"]
        if kind == "function":
            handler = node["config"]["handler"]
            if handler not in registry.functions:
                registry.register_function(handler, _stub_function)
        elif kind == "llm":
            runner = node["config"].get("runner")
            if runner and runner not in registry.llm_runners:
                registry.register_llm_runner(runner, _stub_llm)
        elif kind == "tool":
            tool_ref = node.get("tool_ref")
            if tool_ref and tool_ref not in registry.tools:
                registry.register_tool(tool_ref, _stub_tool)
        elif kind == "retrieval":
            runner = node["config"].get("runner")
            if runner and runner not in registry.retrievals:
                def _stub_retrieval(config: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
                    return {"documents": [{"source": "stub", "score": 0.9, "text": "stub doc"}]}
                registry.register_retrieval(runner, _stub_retrieval)

    return registry, llm_runner_name


def _make_default_registry() -> LocalRegistry:
    registry = LocalRegistry()
    registry.register_function("langgraph_spec_compiler.sample_normalize_input", sample_normalize_input)
    registry.register_function("langgraph_spec_compiler.sample_policy_decide", sample_policy_decide)
    registry.register_llm_runner("langgraph_spec_compiler.example_llm_runner", example_llm_runner)
    registry.register_tool("tasks.create_task", example_local_tool)
    registry.register_retrieval("langgraph_spec_compiler.example_retrieval_runner", example_retrieval_runner)
    return registry


def _print_mermaid(graph: Any) -> None:
    graph_obj = graph.get_graph()
    if hasattr(graph_obj, "draw_mermaid"):
        print(graph_obj.draw_mermaid())
    else:
        print("Mermaid visualization is not available on this LangGraph version.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile minimal Graph Spec JSON into LangGraph")
    parser.add_argument("--spec", type=str, help="Path to Graph Spec JSON")
    parser.add_argument("--write-example", type=str, help="Write bundled example spec JSON to this path")
    parser.add_argument("--print-mermaid", action="store_true", help="Print Mermaid graph if supported")
    parser.add_argument("--invoke", action="store_true", help="Invoke the graph after compilation using --input-json")
    parser.add_argument("--input-json", type=str, help='JSON string passed to graph.invoke, e.g. \'{"input":{"text":"create task"}}\'')
    parser.add_argument("--auto", action="store_true",
                        help="Auto-generate stub handlers for all nodes and run the graph. "
                             "Works with any spec JSON without manual handler registration.")
    args = parser.parse_args()

    if args.write_example:
        path = Path(args.write_example)
        path.write_text(json.dumps(EXAMPLE_SPEC, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote example spec to {path}")
        return

    if not args.spec:
        parser.error("--spec is required unless --write-example is used")

    spec = load_spec(args.spec)

    if args.auto:
        registry, default_llm = _auto_registry_from_spec(spec)
        compiler = GraphSpecCompiler(registry, default_llm_runner=default_llm)
    else:
        registry = _make_default_registry()
        compiler = GraphSpecCompiler(registry)

    graph = compiler.compile_spec(spec)

    print(f"Compiled graph: {spec['graph_id']}")

    if args.print_mermaid:
        _print_mermaid(graph)

    if args.invoke or args.auto:
        payload = json.loads(args.input_json) if args.input_json else {"input": {"text": "test"}}
        config = {"configurable": {"thread_id": "cli-thread-1"}}

        if interrupt is not None:
            # Handle interrupt loops (approval nodes) automatically in --auto mode
            from langgraph.types import Command
            result = graph.invoke(payload, config=config)
            if args.auto:
                for _ in range(10):
                    state = graph.get_state(config)
                    if not state.tasks or not any(t.interrupts for t in state.tasks):
                        break
                    for task in state.tasks:
                        if task.interrupts:
                            print(f"[auto-approve] {task.name}: {task.interrupts[0].value.get('message', '')}")
                            result = graph.invoke(Command(resume={"status": "approved", "comments": []}), config=config)
        else:
            result = graph.invoke(payload, config=config)

        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

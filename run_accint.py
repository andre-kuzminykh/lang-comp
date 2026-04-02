#!/usr/bin/env python3
"""
AccInt Runner — executes AccInt cycles through the graph spec compiler.

Supports two modes:
  1. Single cycle:  python run_accint.py "research AI safety startups"
  2. Father loop:   python run_accint.py --father --domains domain1,domain2

The Father loop continuously selects domains, spawns strategist sessions,
journals results, and starts the next cycle.  It yields to manual work
via a stop file (touch accint_stop).

Environment variables:
  ACCINT_STATE_PATH   — path to scored state file (default: accint_state.json)
  ACCINT_LLM_RUNNER   — LLM runner name (default: stub_llm)
  OPENAI_API_KEY      — if set, uses OpenAI runner instead of stub
  ANTHROPIC_API_KEY   — if set, uses Anthropic runner instead of stub
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from comp import GraphSpecCompiler, LocalRegistry, load_spec
from accint.state_engine import StateEngine
from accint.handlers import set_engine


# ── LLM Runners ─────────────────────────────────────────────

def stub_llm_runner(config: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Stub LLM runner for testing without API keys.

    Produces plausible structured output based on the output_schema
    and the AccInt protocol expectations.
    """
    schema = config.get("output_schema", {})
    node_system = config.get("system_prompt", "")

    # Detect which node we're serving based on the system prompt
    if "Brief Generator" in node_system or "structured brief" in node_system:
        return _stub_brief(inputs)
    elif "Strategist" in node_system:
        return _stub_strategist(inputs)
    elif "Scorer" in node_system or "credit assignment" in node_system:
        return _stub_scorer(inputs)
    else:
        return _stub_generic(schema)


def _stub_brief(inputs: Dict[str, Any]) -> Dict[str, Any]:
    raw = inputs.get("raw_input", {})
    text = raw.get("text", raw.get("objective", "")) if isinstance(raw, dict) else str(raw)
    domain = inputs.get("domain", "general")
    return {
        "title": f"Task: {text[:60]}",
        "domain": domain,
        "objective": text,
        "tags": [domain, "auto-generated"],
        "constraints": [],
        "relevant_entities": [],
        "urgency": "normal",
        "success_criteria": ["Task completed successfully"],
    }


def _stub_strategist(inputs: Dict[str, Any]) -> Dict[str, Any]:
    packet = inputs.get("judgment_packet", {})
    knowledge = packet.get("knowledge", []) if isinstance(packet, dict) else []
    warnings = packet.get("warnings", []) if isinstance(packet, dict) else []

    # Build receipt citing all entries
    applied = []
    dismissed = []
    for k in knowledge:
        if isinstance(k, dict):
            applied.append({"id": k.get("id", ""), "reason": "Relevant to current task"})
    for w in warnings:
        if isinstance(w, dict):
            applied.append({"id": w.get("id", ""), "reason": "Warning acknowledged"})

    objective = inputs.get("objective", "Complete task")
    domain = inputs.get("domain", "general")

    return {
        "receipt": {
            "applied": applied,
            "dismissed": dismissed,
            "noted": [],
        },
        "plan": {
            "objective": objective,
            "approach": f"Execute task in domain '{domain}' using accumulated judgment",
            "steps": [
                "Review scored state",
                "Identify best approach based on prior outcomes",
                "Execute action",
                "Observe and record results",
            ],
            "risks": [w.get("content", "") for w in warnings if isinstance(w, dict)],
            "success_criteria": ["Objective achieved", "New knowledge deposited"],
        },
        "actions": [
            {"action": "researched", "target": domain, "status": "completed"},
        ],
        "observations": [
            f"Cycle executed for domain '{domain}'. {len(knowledge)} knowledge entries consulted.",
        ],
        "new_knowledge": [
            {
                "content": f"Cycle completed for '{objective}' — approach validated",
                "tags": [domain, "cycle-output"],
                "context": f"Domain: {domain}",
            },
        ],
        "new_warnings": [],
        "entity_updates": [],
        "outcome_records": [],
        "pending_outcomes": [],
        "trajectory": {
            "steps": [
                {"step": "compile_judgment", "result": "packet_compiled"},
                {"step": "strategist_reason", "result": "plan_created"},
                {"step": "execute", "result": "completed"},
            ],
            "outcome": "Cycle completed successfully",
            "success": True,
            "tags": [domain],
        },
    }


def _stub_scorer(inputs: Dict[str, Any]) -> Dict[str, Any]:
    return {"assignments": []}


def _stub_generic(schema: Dict[str, Any]) -> Dict[str, Any]:
    props = schema.get("properties", {})
    result = {}
    for key, prop in props.items():
        t = prop.get("type", "string")
        if isinstance(t, list):
            t = t[0]
        if t == "object":
            result[key] = {}
        elif t == "array":
            result[key] = []
        elif t == "boolean":
            result[key] = True
        elif t in ("number", "integer"):
            result[key] = 0
        else:
            result[key] = f"stub_{key}"
    return result or {"stub": True}


# ── OpenAI Runner ────────────────────────────────────────────

def openai_llm_runner(config: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
    """LLM runner using OpenAI API."""
    try:
        from openai import OpenAI
    except ImportError:
        print("openai package not installed, falling back to stub")
        return stub_llm_runner(config, inputs)

    client = OpenAI()
    model = config.get("model", "gpt-4.1")
    # Override non-OpenAI model names
    if "claude" in model or "anthropic" in model:
        model = "gpt-4.1"
    system_prompt = config.get("system_prompt", "You are a helpful assistant.")
    prompt_template = config.get("prompt_template", "")

    # Build user message from inputs
    user_msg = prompt_template
    for key, value in inputs.items():
        placeholder = "{{" + key + "}}"
        if placeholder in user_msg:
            user_msg = user_msg.replace(
                placeholder,
                json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value,
            )

    if not user_msg.strip():
        user_msg = json.dumps(inputs, ensure_ascii=False, default=str)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt + "\n\nAlways respond with valid JSON."},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )

    text = response.choices[0].message.content
    print(f"\n  [OpenAI response preview] {text[:300]}...")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(f"  [OpenAI parse error] Could not parse JSON")
        return {"raw_response": text, "parse_error": True}


# ── Anthropic Runner ─────────────────────────────────────────

def anthropic_llm_runner(config: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
    """LLM runner using Anthropic API."""
    try:
        import anthropic
    except ImportError:
        print("anthropic package not installed, falling back to stub")
        return stub_llm_runner(config, inputs)

    client = anthropic.Anthropic()
    model = config.get("model", "claude-sonnet-4-20250514")
    system_prompt = config.get("system_prompt", "You are a helpful assistant.")
    prompt_template = config.get("prompt_template", "")

    # Build user message from inputs
    user_msg = prompt_template
    for key, value in inputs.items():
        placeholder = "{{" + key + "}}"
        if placeholder in user_msg:
            user_msg = user_msg.replace(
                placeholder,
                json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value,
            )

    if not user_msg.strip():
        user_msg = json.dumps(inputs, ensure_ascii=False, default=str)

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt + "\n\nAlways respond with valid JSON only. No markdown fences.",
        messages=[{"role": "user", "content": user_msg}],
        temperature=0.3,
    )

    text = response.content[0].text
    # Strip markdown fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw_response": text, "parse_error": True}


# ── Build registry ───────────────────────────────────────────

def make_registry(llm_runner_name: str = "stub") -> LocalRegistry:
    registry = LocalRegistry()

    # Select LLM runner
    if llm_runner_name == "openai":
        registry.register_llm_runner("accint_llm", openai_llm_runner)
    elif llm_runner_name == "anthropic":
        registry.register_llm_runner("accint_llm", anthropic_llm_runner)
    else:
        registry.register_llm_runner("accint_llm", stub_llm_runner)

    # Register AccInt function handlers
    from accint.handlers import (
        begin_cycle,
        compile_judgment,
        validate_receipt,
        persist_knowledge,
        check_self_improvement,
        close_cycle,
    )

    registry.register_function("accint.handlers.begin_cycle", begin_cycle)
    registry.register_function("accint.handlers.compile_judgment", compile_judgment)
    registry.register_function("accint.handlers.validate_receipt", validate_receipt)
    registry.register_function("accint.handlers.persist_knowledge", persist_knowledge)
    registry.register_function("accint.handlers.check_self_improvement", check_self_improvement)
    registry.register_function("accint.handlers.close_cycle", close_cycle)

    return registry


# ── Single cycle ─────────────────────────────────────────────

def run_single_cycle(
    objective: str,
    domain: str = "general",
    state_path: str = "accint_state.json",
    llm_runner: str = "stub",
) -> Dict[str, Any]:
    """Run a single AccInt cycle."""
    engine = StateEngine(state_path)
    set_engine(engine)

    registry = make_registry(llm_runner)
    spec = load_spec(Path(__file__).parent / "accint" / "accint_graph.json")
    compiler = GraphSpecCompiler(
        registry,
        default_llm_runner="accint_llm",
    )
    graph = compiler.compile_spec(spec)

    payload = {
        "input": {
            "text": objective,
            "domain": domain,
            "objective": objective,
        }
    }
    config = {"configurable": {"thread_id": f"accint-{engine.data['cycle_count'] + 1}"}}

    print(f"\n{'='*60}")
    print(f"AccInt Cycle")
    print(f"Domain:    {domain}")
    print(f"Objective: {objective}")
    print(f"State:     {state_path}")
    print(f"LLM:       {llm_runner}")
    print(f"{'='*60}\n")

    result = graph.invoke(payload, config=config)

    # Handle interrupts (shouldn't normally happen in AccInt cycle)
    max_iter = 5
    for _ in range(max_iter):
        state = graph.get_state(config)
        if not state.tasks or not any(t.interrupts for t in state.tasks):
            break
        for task in state.tasks:
            if task.interrupts:
                from langgraph.types import Command
                result = graph.invoke(
                    Command(resume={"status": "approved"}),
                    config=config,
                )

    summary = result.get("cycle_summary", {})
    print(f"\n{'─'*60}")
    print("Cycle Summary:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"{'─'*60}")

    stats = engine.stats()
    print(f"\nAccumulated State:")
    print(f"  Cycles:      {stats['cycles']}")
    print(f"  Knowledge:   {stats['knowledge_entries']}")
    print(f"  Warnings:    {stats['warnings']}")
    print(f"  Entities:    {stats['entities']}")
    print(f"  Trajectories:{stats['trajectories']}")
    print(f"  Outcomes:    {stats['outcomes']}")

    return result


# ── Father loop ──────────────────────────────────────────────

def run_father_loop(
    domains: list[str],
    state_path: str = "accint_state.json",
    llm_runner: str = "stub",
    cycle_delay: float = 5.0,
    max_cycles: int = 0,
):
    """Father — the continuous supervisor.

    Rotates through domains, running one AccInt cycle per domain.
    Stops when:
      - accint_stop file exists (graceful shutdown)
      - max_cycles reached (if > 0)
      - KeyboardInterrupt
    """
    stop_file = Path("accint_stop")
    engine = StateEngine(state_path)

    print(f"\n{'='*60}")
    print("Father — AccInt Continuous Supervisor")
    print(f"Domains:    {', '.join(domains)}")
    print(f"State:      {state_path}")
    print(f"LLM:        {llm_runner}")
    print(f"Stop file:  {stop_file}")
    if max_cycles > 0:
        print(f"Max cycles: {max_cycles}")
    print(f"{'='*60}\n")

    cycle_count = 0
    domain_idx = 0

    try:
        while True:
            # Check for graceful stop
            if stop_file.exists():
                print("\n[Father] Stop file detected. Shutting down gracefully.")
                stop_file.unlink()
                break

            # Check max cycles
            if max_cycles > 0 and cycle_count >= max_cycles:
                print(f"\n[Father] Max cycles ({max_cycles}) reached. Stopping.")
                break

            # Select domain (round-robin; a real implementation would use
            # the domain selector prompt to pick by priority)
            domain = domains[domain_idx % len(domains)]
            domain_idx += 1

            objective = f"Continue work in domain '{domain}' — check pending outcomes, advance active goals"

            print(f"\n[Father] Cycle {cycle_count + 1} — Domain: {domain}")

            try:
                run_single_cycle(
                    objective=objective,
                    domain=domain,
                    state_path=state_path,
                    llm_runner=llm_runner,
                )
            except Exception as e:
                print(f"\n[Father] Cycle error: {e}")
                engine.journal_entry(
                    engine.data["cycle_count"],
                    "cycle_error",
                    {"error": str(e), "domain": domain},
                )

            cycle_count += 1

            if cycle_delay > 0:
                print(f"\n[Father] Next cycle in {cycle_delay}s...")
                time.sleep(cycle_delay)

    except KeyboardInterrupt:
        print("\n\n[Father] Interrupted by user. Shutting down.")

    print(f"\n[Father] Completed {cycle_count} cycles.")
    print(f"[Father] Final state: {json.dumps(engine.stats(), indent=2)}")


# ── CLI ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AccInt — Accreted Intelligence Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Single cycle with stub LLM:
  python run_accint.py "Research AI safety startups"

  # Single cycle with real LLM:
  python run_accint.py "Research AI safety startups" --llm anthropic

  # Father continuous loop:
  python run_accint.py --father --domains outreach,research,operations

  # Stop Father gracefully:
  touch accint_stop
""",
    )
    parser.add_argument("objective", nargs="?", default=None, help="Task objective")
    parser.add_argument("--domain", default="general", help="Domain (default: general)")
    parser.add_argument("--state", default="accint_state.json", help="State file path")
    parser.add_argument(
        "--llm",
        default="stub",
        choices=["stub", "openai", "anthropic"],
        help="LLM runner (default: stub)",
    )
    parser.add_argument("--father", action="store_true", help="Run Father continuous loop")
    parser.add_argument("--domains", default="general", help="Comma-separated domains for Father")
    parser.add_argument("--delay", type=float, default=5.0, help="Delay between Father cycles (seconds)")
    parser.add_argument("--max-cycles", type=int, default=0, help="Max cycles for Father (0=unlimited)")
    parser.add_argument("--stats", action="store_true", help="Show state statistics and exit")
    parser.add_argument("--dump-state", action="store_true", help="Dump full state and exit")
    parser.add_argument(
        "--add-directive",
        default=None,
        help="Add an owner directive to the state",
    )

    args = parser.parse_args()

    # Auto-detect LLM runner from environment
    llm_runner = args.llm
    if llm_runner == "stub":
        if os.environ.get("ANTHROPIC_API_KEY"):
            llm_runner = "anthropic"
            print("[Auto-detected Anthropic API key]")
        elif os.environ.get("OPENAI_API_KEY"):
            llm_runner = "openai"
            print("[Auto-detected OpenAI API key]")

    # Stats mode
    if args.stats:
        engine = StateEngine(args.state)
        print(json.dumps(engine.stats(), indent=2))
        return

    # Dump state mode
    if args.dump_state:
        engine = StateEngine(args.state)
        print(json.dumps(engine.data, ensure_ascii=False, indent=2))
        return

    # Add directive
    if args.add_directive:
        engine = StateEngine(args.state)
        did = engine.add_directive(args.add_directive)
        print(f"Directive added: {did}")
        print(f"  Content: {args.add_directive}")
        return

    # Father mode
    if args.father:
        domains = [d.strip() for d in args.domains.split(",") if d.strip()]
        if not domains:
            domains = ["general"]
        run_father_loop(
            domains=domains,
            state_path=args.state,
            llm_runner=llm_runner,
            cycle_delay=args.delay,
            max_cycles=args.max_cycles,
        )
        return

    # Single cycle
    if not args.objective:
        parser.print_help()
        print("\nError: objective is required for single cycle mode")
        sys.exit(1)

    run_single_cycle(
        objective=args.objective,
        domain=args.domain,
        state_path=args.state,
        llm_runner=llm_runner,
    )


if __name__ == "__main__":
    main()

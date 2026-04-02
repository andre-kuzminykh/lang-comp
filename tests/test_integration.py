"""Integration tests — run full AccInt cycles through the graph compiler."""

import json
import pytest
from pathlib import Path

from comp import GraphSpecCompiler, LocalRegistry, load_spec
from accint.state_engine import StateEngine
from accint.handlers import set_engine


def _stub_llm(config, inputs):
    """Minimal LLM stub producing valid AccInt protocol output."""
    system = config.get("system_prompt", "")
    if "Brief Generator" in system or "structured brief" in system:
        raw = inputs.get("raw_input", {})
        text = raw.get("objective", "") if isinstance(raw, dict) else str(raw)
        return {
            "title": f"Task: {text[:40]}",
            "domain": inputs.get("domain", "test"),
            "objective": text,
            "tags": ["test", "integration"],
            "constraints": [],
            "relevant_entities": [],
            "urgency": "normal",
            "success_criteria": ["done"],
        }
    elif "Strategist" in system:
        packet = inputs.get("judgment_packet", {})
        knowledge = packet.get("knowledge", []) if isinstance(packet, dict) else []
        warnings = packet.get("warnings", []) if isinstance(packet, dict) else []
        applied = [{"id": k["id"], "reason": "used"} for k in knowledge if isinstance(k, dict)]
        applied += [{"id": w["id"], "reason": "warning ack"} for w in warnings if isinstance(w, dict)]
        return {
            "receipt": {"applied": applied, "dismissed": [], "noted": []},
            "plan": {"objective": "test objective", "steps": ["step1"]},
            "actions": [{"action": "tested"}],
            "observations": ["observed"],
            "new_knowledge": [{"content": "integration test insight", "tags": ["test"]}],
            "new_warnings": [],
            "entity_updates": [
                {"name": "TestCorp", "type": "org", "attributes": {"kind": "test"},
                 "tags": ["test"], "interaction": {"action": "contacted"}},
            ],
            "outcome_records": [],
            "pending_outcomes": [
                {"description": "check later", "related_entry_ids": [], "check_after_cycles": 2},
            ],
            "trajectory": {
                "steps": [{"step": "plan"}, {"step": "execute"}],
                "outcome": "success",
                "success": True,
                "tags": ["test"],
            },
        }
    elif "Scorer" in system or "credit" in system:
        return {"assignments": []}
    else:
        return {"stub": True}


def _make_graph(engine):
    set_engine(engine)
    registry = LocalRegistry()
    registry.register_llm_runner("test_llm", _stub_llm)
    from accint.handlers import (
        begin_cycle, compile_judgment, validate_receipt,
        persist_knowledge, check_self_improvement, close_cycle,
    )
    registry.register_function("accint.handlers.begin_cycle", begin_cycle)
    registry.register_function("accint.handlers.compile_judgment", compile_judgment)
    registry.register_function("accint.handlers.validate_receipt", validate_receipt)
    registry.register_function("accint.handlers.persist_knowledge", persist_knowledge)
    registry.register_function("accint.handlers.check_self_improvement", check_self_improvement)
    registry.register_function("accint.handlers.close_cycle", close_cycle)

    spec = load_spec(Path(__file__).parent.parent / "accint" / "accint_graph.json")
    compiler = GraphSpecCompiler(registry, default_llm_runner="test_llm")
    return compiler.compile_spec(spec)


class TestFullCycle:
    def test_single_cycle(self, tmp_path):
        engine = StateEngine(tmp_path / "state.json")
        graph = _make_graph(engine)
        payload = {"input": {"text": "test task", "domain": "test", "objective": "test task"}}
        config = {"configurable": {"thread_id": "test-1"}}
        result = graph.invoke(payload, config=config)

        assert "cycle_summary" in result
        summary = result["cycle_summary"]
        assert summary["cycle"] == 1
        assert summary["domain"] == "test"
        assert summary["knowledge_deposited"] >= 1

        # State should have accumulated
        stats = engine.stats()
        assert stats["cycles"] == 1
        assert stats["knowledge_entries"] >= 1
        assert stats["trajectories"] >= 1

    def test_knowledge_compounds_across_cycles(self, tmp_path):
        engine = StateEngine(tmp_path / "state.json")
        graph = _make_graph(engine)

        for i in range(3):
            payload = {"input": {"text": f"task {i}", "domain": "test", "objective": f"task {i}"}}
            config = {"configurable": {"thread_id": f"test-{i}"}}
            result = graph.invoke(payload, config=config)

        stats = engine.stats()
        assert stats["cycles"] == 3
        assert stats["knowledge_entries"] >= 3
        assert stats["trajectories"] >= 3

    def test_judgment_packet_grows(self, tmp_path):
        """After multiple cycles, the judgment packet should contain prior knowledge."""
        engine = StateEngine(tmp_path / "state.json")

        # Seed some knowledge
        engine.add_knowledge("prior insight 1", ["test"])
        engine.add_knowledge("prior insight 2", ["test"])
        engine.add_warning("prior warning", ["test"])

        graph = _make_graph(engine)
        payload = {"input": {"text": "new task", "domain": "test", "objective": "new task"}}
        config = {"configurable": {"thread_id": "test-growth"}}
        result = graph.invoke(payload, config=config)

        # The strategist stub should have received the prior knowledge
        # and produced a valid receipt — if receipt validation failed,
        # the cycle would loop back.  Since we get a summary, it passed.
        assert result["cycle_summary"]["cycle"] == 1

    def test_entities_persist(self, tmp_path):
        engine = StateEngine(tmp_path / "state.json")
        graph = _make_graph(engine)
        payload = {"input": {"text": "contact people", "domain": "test", "objective": "contact"}}
        config = {"configurable": {"thread_id": "test-entity"}}
        graph.invoke(payload, config=config)

        assert len(engine.data["entities"]) >= 1
        assert engine.data["entities"][0]["name"] == "TestCorp"

    def test_pending_outcomes_stored(self, tmp_path):
        engine = StateEngine(tmp_path / "state.json")
        graph = _make_graph(engine)
        payload = {"input": {"text": "do thing", "domain": "test", "objective": "thing"}}
        config = {"configurable": {"thread_id": "test-pending"}}
        graph.invoke(payload, config=config)

        assert len(engine.data["pending_outcomes"]) >= 1

    def test_recipes_auto_compiled(self, tmp_path):
        engine = StateEngine(tmp_path / "state.json")
        graph = _make_graph(engine)
        payload = {"input": {"text": "do thing", "domain": "test", "objective": "thing"}}
        config = {"configurable": {"thread_id": "test-recipe"}}
        graph.invoke(payload, config=config)

        assert len(engine.data["recipes"]) >= 1
        assert engine.data["recipes"][0]["status"] == "active"

    def test_cost_tier_tracked(self, tmp_path):
        engine = StateEngine(tmp_path / "state.json")
        graph = _make_graph(engine)
        payload = {"input": {"text": "do thing", "domain": "test", "objective": "thing"}}
        config = {"configurable": {"thread_id": "test-cost"}}
        graph.invoke(payload, config=config)

        dist = engine.get_cost_distribution()
        assert dist["tier_3_reasoning"] >= 1  # Full reasoning cycle

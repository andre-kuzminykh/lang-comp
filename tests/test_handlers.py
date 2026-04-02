"""Tests for accint.handlers — graph node function handlers."""

import pytest

from accint.state_engine import StateEngine
from accint.handlers import (
    set_engine,
    begin_cycle,
    compile_judgment,
    validate_receipt,
    persist_knowledge,
    check_self_improvement,
    close_cycle,
)


@pytest.fixture
def engine(tmp_path):
    path = tmp_path / "test_handlers.json"
    e = StateEngine(path)
    set_engine(e)
    return e


class TestBeginCycle:
    def test_increments_cycle(self, engine):
        result = begin_cycle({"input": {"domain": "test", "objective": "do stuff"}})
        assert result["cycle_number"] == 1
        assert result["domain"] == "test"
        assert result["objective"] == "do stuff"

    def test_default_domain(self, engine):
        result = begin_cycle({"input": {"text": "hello"}})
        assert result["domain"] == "general"
        assert result["objective"] == "hello"


class TestCompileJudgment:
    def test_compiles_packet(self, engine):
        engine.add_knowledge("test insight", ["research"])
        engine.add_warning("test warning", ["research"])
        engine.begin_cycle()
        result = compile_judgment({
            "brief": {"tags": ["research"]}
        })
        assert len(result["knowledge"]) == 1
        assert len(result["warnings"]) == 1

    def test_empty_tags(self, engine):
        result = compile_judgment({"brief": {}})
        assert "knowledge" in result
        assert "warnings" in result


class TestValidateReceipt:
    def test_valid_receipt(self, engine):
        kid = engine.add_knowledge("insight", ["tag"])
        wid = engine.add_warning("warning", ["tag"])
        result = validate_receipt({
            "strategist_output": {
                "receipt": {
                    "applied": [{"id": kid, "reason": "used"}],
                    "dismissed": [{"id": wid, "reason": "not relevant"}],
                    "noted": [],
                }
            },
            "judgment_packet": {
                "knowledge": [{"id": kid}],
                "warnings": [{"id": wid}],
            },
        })
        assert result["valid"] is True
        assert result["applied_count"] == 1

    def test_missing_citations(self, engine):
        kid = engine.add_knowledge("insight", ["tag"])
        result = validate_receipt({
            "strategist_output": {
                "receipt": {
                    "applied": [],
                    "dismissed": [],
                    "noted": [],
                }
            },
            "judgment_packet": {
                "knowledge": [{"id": kid}],
                "warnings": [],
            },
        })
        assert result["valid"] is False
        assert kid in result["missing_ids"]

    def test_no_receipt(self, engine):
        result = validate_receipt({
            "strategist_output": {},
            "judgment_packet": {"knowledge": [], "warnings": []},
        })
        assert result["valid"] is False

    def test_records_usage_for_applied(self, engine):
        kid = engine.add_knowledge("insight", ["tag"])
        validate_receipt({
            "strategist_output": {
                "receipt": {
                    "applied": [{"id": kid, "reason": "used"}],
                    "dismissed": [],
                    "noted": [],
                }
            },
            "judgment_packet": {
                "knowledge": [{"id": kid}],
                "warnings": [],
            },
        })
        from accint.scoring import BetaScore
        entry = engine._find_entry(kid)
        bs = BetaScore.from_dict(entry["score"])
        assert bs.usage_count == 1


class TestPersistKnowledge:
    def test_stores_new_knowledge(self, engine):
        engine.begin_cycle()
        result = persist_knowledge({
            "strategist_output": {
                "new_knowledge": [
                    {"content": "new insight", "tags": ["research"]},
                ],
                "new_warnings": [],
                "entity_updates": [],
                "outcome_records": [],
                "pending_outcomes": [],
            },
            "credit_assignments": [],
            "cycle_number": 1,
        })
        assert len(result["knowledge_ids"]) == 1
        assert len(engine.data["knowledge"]) == 1

    def test_stores_warnings(self, engine):
        engine.begin_cycle()
        result = persist_knowledge({
            "strategist_output": {
                "new_knowledge": [],
                "new_warnings": [
                    {"content": "this failed", "tags": ["outreach"]},
                ],
                "entity_updates": [],
                "outcome_records": [],
                "pending_outcomes": [],
            },
            "credit_assignments": [],
            "cycle_number": 1,
        })
        assert len(result["warning_ids"]) == 1

    def test_stores_entity_updates(self, engine):
        engine.begin_cycle()
        persist_knowledge({
            "strategist_output": {
                "new_knowledge": [],
                "new_warnings": [],
                "entity_updates": [
                    {
                        "name": "Alice Corp",
                        "type": "org",
                        "attributes": {"sector": "AI"},
                        "interaction": {"action": "researched", "outcome": "found"},
                    },
                ],
                "outcome_records": [],
                "pending_outcomes": [],
            },
            "credit_assignments": [],
            "cycle_number": 1,
        })
        assert len(engine.data["entities"]) == 1
        assert len(engine.data["entities"][0]["interactions"]) == 1

    def test_stores_pending_outcomes(self, engine):
        engine.begin_cycle()
        persist_knowledge({
            "strategist_output": {
                "new_knowledge": [],
                "new_warnings": [],
                "entity_updates": [],
                "outcome_records": [],
                "pending_outcomes": [
                    {
                        "description": "check if reply received",
                        "related_entry_ids": [],
                        "check_after_cycles": 3,
                    },
                ],
            },
            "credit_assignments": [],
            "cycle_number": 1,
        })
        assert len(engine.data["pending_outcomes"]) == 1

    def test_applies_credit_assignments(self, engine):
        engine.begin_cycle()
        kid = engine.add_knowledge("approach", ["tag"])
        persist_knowledge({
            "strategist_output": {
                "new_knowledge": [],
                "new_warnings": [],
                "entity_updates": [],
                "outcome_records": [],
                "pending_outcomes": [],
            },
            "credit_assignments": [
                {"entry_id": kid, "success": True, "weight": 1.0},
            ],
            "cycle_number": 1,
        })
        from accint.scoring import BetaScore
        entry = engine._find_entry(kid)
        bs = BetaScore.from_dict(entry["score"])
        assert bs.alpha == 2.0

    def test_stores_trajectory_and_recipe(self, engine):
        engine.begin_cycle()
        persist_knowledge({
            "strategist_output": {
                "new_knowledge": [],
                "new_warnings": [],
                "entity_updates": [],
                "outcome_records": [],
                "pending_outcomes": [],
                "trajectory": {
                    "steps": [{"step": "research"}, {"step": "contact"}],
                    "outcome": "success",
                    "success": True,
                    "tags": ["outreach"],
                },
            },
            "credit_assignments": [],
            "cycle_number": 1,
        })
        assert len(engine.data["trajectories"]) == 1
        assert len(engine.data["recipes"]) == 1  # auto-promoted


class TestCheckSelfImprovement:
    def test_no_proposals(self, engine):
        result = check_self_improvement({
            "strategist_output": {"plan": {}},
            "cycle_number": 1,
        })
        assert result["has_proposals"] is False

    def test_proposals_logged_but_not_approved(self, engine):
        engine.begin_cycle()
        result = check_self_improvement({
            "strategist_output": {
                "plan": {
                    "proposed_improvements": [
                        {"description": "Change scoring threshold to 0.7"},
                    ],
                },
            },
            "cycle_number": 1,
        })
        assert result["has_proposals"] is True
        assert result["proposals"][0]["approved"] is False
        # Should be recorded as warning
        assert len(engine.data["warnings"]) == 1


class TestCloseCycle:
    def test_produces_summary(self, engine):
        engine.begin_cycle()
        result = close_cycle({
            "cycle_number": 1,
            "domain": "research",
            "strategist_output": {"plan": {"objective": "do research"}},
            "new_knowledge_ids": ["a", "b"],
            "new_warning_ids": ["c"],
            "credit_assignments": [{"entry_id": "x", "success": True}],
            "governance_check": {"proposals": []},
        })
        assert result["cycle"] == 1
        assert result["domain"] == "research"
        assert result["knowledge_deposited"] == 2
        assert result["warnings_deposited"] == 1
        assert "stats" in result

"""Tests for accint.state_engine — scored external state store."""

import os
import pytest
import time

from accint.state_engine import StateEngine
from accint.scoring import BetaScore


@pytest.fixture
def engine(tmp_path):
    """Fresh state engine backed by a temp file."""
    path = tmp_path / "test_state.json"
    return StateEngine(path)


class TestPersistence:
    def test_creates_empty_state(self, engine):
        assert engine.data["cycle_count"] == 0
        assert engine.data["knowledge"] == []
        assert engine.data["version"] == 1

    def test_save_and_reload(self, tmp_path):
        path = tmp_path / "persist.json"
        e1 = StateEngine(path)
        e1.add_knowledge("test", ["tag"])
        e1.begin_cycle()

        e2 = StateEngine(path)
        assert len(e2.data["knowledge"]) == 1
        assert e2.data["cycle_count"] == 1

    def test_atomic_save(self, tmp_path):
        path = tmp_path / "atomic.json"
        engine = StateEngine(path)
        engine.add_knowledge("test", ["tag"])
        assert path.exists()
        assert not path.with_suffix(".tmp").exists()


class TestKnowledge:
    def test_add_knowledge(self, engine):
        kid = engine.add_knowledge("warmth before competence", ["social", "outreach"])
        assert kid is not None
        assert len(engine.data["knowledge"]) == 1
        entry = engine.data["knowledge"][0]
        assert entry["content"] == "warmth before competence"
        assert "social" in entry["tags"]
        assert entry["kind"] == "knowledge"

    def test_add_warning(self, engine):
        wid = engine.add_warning("cold pitch triggers resistance", ["outreach"])
        assert len(engine.data["warnings"]) == 1
        entry = engine.data["warnings"][0]
        assert entry["kind"] == "warning"

    def test_record_usage(self, engine):
        kid = engine.add_knowledge("test", ["tag"])
        engine.record_usage(kid)
        entry = engine._find_entry(kid)
        assert entry is not None
        bs = BetaScore.from_dict(entry["score"])
        assert bs.usage_count == 1
        assert bs.last_used > 0

    def test_record_outcome_success(self, engine):
        kid = engine.add_knowledge("test approach", ["tag"])
        engine.record_outcome(kid, success=True)
        entry = engine._find_entry(kid)
        bs = BetaScore.from_dict(entry["score"])
        assert bs.alpha == 2.0  # prior + 1 success

    def test_record_outcome_failure(self, engine):
        kid = engine.add_knowledge("risky approach", ["tag"])
        engine.record_outcome(kid, success=False)
        entry = engine._find_entry(kid)
        bs = BetaScore.from_dict(entry["score"])
        assert bs.beta == 2.0  # prior + 1 failure

    def test_invalid_kind_raises(self, engine):
        with pytest.raises(ValueError, match="Unknown entry kind"):
            engine.add_knowledge("test", ["tag"], kind="invalid")


class TestEntities:
    def test_upsert_entity(self, engine):
        eid = engine.upsert_entity("John Doe", "person", {"role": "CTO"}, ["outreach"])
        assert len(engine.data["entities"]) == 1
        assert engine.data["entities"][0]["name"] == "John Doe"
        assert engine.data["entities"][0]["attributes"]["role"] == "CTO"

    def test_upsert_updates_existing(self, engine):
        eid1 = engine.upsert_entity("John Doe", "person", {"role": "CTO"})
        eid2 = engine.upsert_entity("john doe", "person", {"company": "Acme"})
        assert eid1 == eid2
        assert len(engine.data["entities"]) == 1
        ent = engine.data["entities"][0]
        assert ent["attributes"]["role"] == "CTO"
        assert ent["attributes"]["company"] == "Acme"

    def test_record_entity_interaction(self, engine):
        eid = engine.upsert_entity("Jane", "person")
        engine.record_entity_interaction(
            eid, action="sent_email", outcome="replied", channel="gmail"
        )
        ent = engine.data["entities"][0]
        assert len(ent["interactions"]) == 1
        assert ent["interactions"][0]["action"] == "sent_email"
        assert ent["interactions"][0]["channel"] == "gmail"


class TestTrajectories:
    def test_record_trajectory(self, engine):
        tid = engine.record_trajectory(
            steps=[{"step": "research"}, {"step": "outreach"}],
            outcome="positive response",
            success=True,
            tags=["outreach"],
        )
        assert len(engine.data["trajectories"]) == 1
        traj = engine.data["trajectories"][0]
        assert traj["success"] is True
        bs = BetaScore.from_dict(traj["score"])
        assert bs.alpha == 2.0  # boosted for success

    def test_failed_trajectory_scored_lower(self, engine):
        engine.record_trajectory(
            steps=[{"step": "cold_call"}],
            outcome="rejected",
            success=False,
            tags=["outreach"],
        )
        traj = engine.data["trajectories"][0]
        bs = BetaScore.from_dict(traj["score"])
        assert bs.beta == 2.0  # penalized for failure


class TestOutcomes:
    def test_record_observed_outcome(self, engine):
        kid = engine.add_knowledge("approach A", ["tag"])
        oid = engine.record_observed_outcome(
            description="Approach A worked",
            related_entry_ids=[kid],
            success=True,
            evidence="Client replied positively",
        )
        assert len(engine.data["outcomes"]) == 1
        # Credit should propagate to knowledge entry
        entry = engine._find_entry(kid)
        bs = BetaScore.from_dict(entry["score"])
        assert bs.alpha == 2.0  # got success credit


class TestPendingOutcomes:
    def test_add_pending_outcome(self, engine):
        engine.begin_cycle()  # cycle 1
        kid = engine.add_knowledge("long-term approach", ["tag"])
        pid = engine.add_pending_outcome(
            description="Check if partnership formed",
            related_entry_ids=[kid],
            check_after_cycles=3,
        )
        assert len(engine.data["pending_outcomes"]) == 1
        po = engine.data["pending_outcomes"][0]
        assert po["check_after_cycle"] == 4  # current(1) + 3
        assert po["resolved"] is False

    def test_get_due_pending_outcomes(self, engine):
        for _ in range(5):
            engine.begin_cycle()
        kid = engine.add_knowledge("test", ["tag"])
        engine.add_pending_outcome("early", [kid], check_after_cycles=0)
        engine.add_pending_outcome("later", [kid], check_after_cycles=100)
        due = engine.get_due_pending_outcomes()
        assert len(due) == 1
        assert due[0]["description"] == "early"

    def test_resolve_pending_outcome(self, engine):
        engine.begin_cycle()
        kid = engine.add_knowledge("tested approach", ["tag"])
        pid = engine.add_pending_outcome("check result", [kid], check_after_cycles=0)
        engine.resolve_pending_outcome(pid, success=True, evidence="confirmed")
        po = engine.data["pending_outcomes"][0]
        assert po["resolved"] is True
        assert po["resolution"]["success"] is True
        # Credit should propagate
        entry = engine._find_entry(kid)
        bs = BetaScore.from_dict(entry["score"])
        assert bs.alpha > 1.0


class TestRecipes:
    def test_compile_recipe_from_trajectory(self, engine):
        tid = engine.record_trajectory(
            steps=[{"step": "login"}, {"step": "send_dm"}],
            outcome="dm sent",
            success=True,
            tags=["instagram"],
        )
        rid = engine.compile_recipe(tid, "ig_send_dm", tags=["instagram"])
        assert rid is not None
        assert len(engine.data["recipes"]) == 1
        recipe = engine.data["recipes"][0]
        assert recipe["status"] == "active"
        assert recipe["steps"] == [{"step": "login"}, {"step": "send_dm"}]

    def test_compile_recipe_rejects_failed_trajectory(self, engine):
        tid = engine.record_trajectory(
            steps=[{"step": "fail"}],
            outcome="crashed",
            success=False,
            tags=["test"],
        )
        rid = engine.compile_recipe(tid, "bad_recipe")
        assert rid is None

    def test_get_recipe_by_tags(self, engine):
        tid = engine.record_trajectory(
            steps=[{"step": "a"}], outcome="ok", success=True, tags=["email"]
        )
        engine.compile_recipe(tid, "email_recipe", tags=["email"])
        recipe = engine.get_recipe(["email"])
        assert recipe is not None
        assert recipe["name"] == "email_recipe"

    def test_recipe_quarantine_on_poor_performance(self, engine):
        tid = engine.record_trajectory(
            steps=[{"step": "a"}], outcome="ok", success=True, tags=["test"]
        )
        rid = engine.compile_recipe(tid, "fragile_recipe", tags=["test"])
        # Record many failures
        for _ in range(10):
            engine.record_recipe_outcome(rid, success=False)
        recipe = engine.data["recipes"][0]
        assert recipe["status"] == "quarantined"

    def test_recipe_replay_count(self, engine):
        tid = engine.record_trajectory(
            steps=[{"step": "a"}], outcome="ok", success=True, tags=["test"]
        )
        rid = engine.compile_recipe(tid, "counted_recipe", tags=["test"])
        engine.record_recipe_outcome(rid, success=True)
        engine.record_recipe_outcome(rid, success=True)
        assert engine.data["recipes"][0]["replay_count"] == 2


class TestRelationships:
    def test_add_relationship(self, engine):
        ea = engine.upsert_entity("Alice", "person")
        eb = engine.upsert_entity("Bob", "person")
        rid = engine.add_relationship(ea, eb, "collaborator", {"project": "X"})
        assert len(engine.data["relationships"]) == 1
        rel = engine.data["relationships"][0]
        assert rel["relation_type"] == "collaborator"
        assert rel["attributes"]["project"] == "X"

    def test_upsert_relationship(self, engine):
        ea = engine.upsert_entity("Alice", "person")
        eb = engine.upsert_entity("Bob", "person")
        rid1 = engine.add_relationship(ea, eb, "collaborator")
        rid2 = engine.add_relationship(ea, eb, "collaborator", {"trust": "high"})
        assert rid1 == rid2
        assert len(engine.data["relationships"]) == 1
        assert engine.data["relationships"][0]["attributes"]["trust"] == "high"

    def test_get_entity_relationships(self, engine):
        ea = engine.upsert_entity("Alice", "person")
        eb = engine.upsert_entity("Bob", "person")
        ec = engine.upsert_entity("Carol", "person")
        engine.add_relationship(ea, eb, "knows")
        engine.add_relationship(ea, ec, "manages")
        rels = engine.get_entity_relationships(ea)
        assert len(rels) == 2

    def test_relationship_scoring(self, engine):
        ea = engine.upsert_entity("A", "person")
        eb = engine.upsert_entity("B", "person")
        rid = engine.add_relationship(ea, eb, "partner")
        engine.record_relationship_outcome(rid, success=True)
        engine.record_relationship_outcome(rid, success=True)
        engine.record_relationship_outcome(rid, success=False)
        rel = engine.data["relationships"][0]
        bs = BetaScore.from_dict(rel["score"])
        assert bs.alpha == 3.0
        assert bs.beta == 2.0


class TestCostTiers:
    def test_record_execution_tier(self, engine):
        engine.record_execution_tier(0)
        engine.record_execution_tier(0)
        engine.record_execution_tier(3)
        dist = engine.get_cost_distribution()
        assert dist["tier_0_cached"] == 2
        assert dist["tier_3_reasoning"] == 1

    def test_cost_compression_ratio(self, engine):
        engine.record_execution_tier(0)
        engine.record_execution_tier(0)
        engine.record_execution_tier(0)
        engine.record_execution_tier(3)
        ratio = engine.get_cost_compression_ratio()
        assert ratio == 3.0  # 3 cheap / 1 expensive

    def test_cost_compression_no_expensive(self, engine):
        engine.record_execution_tier(0)
        ratio = engine.get_cost_compression_ratio()
        assert ratio == float("inf")

    def test_cost_compression_no_data(self, engine):
        ratio = engine.get_cost_compression_ratio()
        assert ratio == 0.0


class TestJudgmentPacket:
    def test_compile_empty(self, engine):
        packet = engine.compile_judgment_packet(["nonexistent"])
        assert packet["knowledge"] == []
        assert packet["warnings"] == []
        assert packet["entities"] == []

    def test_compile_filters_by_tags(self, engine):
        engine.add_knowledge("relevant", ["outreach"])
        engine.add_knowledge("irrelevant", ["internal"])
        packet = engine.compile_judgment_packet(["outreach"])
        assert len(packet["knowledge"]) == 1
        assert packet["knowledge"][0]["content"] == "relevant"

    def test_compile_includes_warnings(self, engine):
        engine.add_warning("dangerous approach", ["outreach"])
        packet = engine.compile_judgment_packet(["outreach"])
        assert len(packet["warnings"]) == 1

    def test_compile_includes_directives(self, engine):
        engine.add_directive("Focus on B2B")
        packet = engine.compile_judgment_packet([])
        assert len(packet["directives"]) == 1

    def test_compile_includes_entities(self, engine):
        engine.upsert_entity("Alice", "person", tags=["outreach"])
        packet = engine.compile_judgment_packet(["outreach"])
        assert len(packet["entities"]) == 1

    def test_compile_includes_relationships(self, engine):
        ea = engine.upsert_entity("Alice", "person", tags=["outreach"])
        eb = engine.upsert_entity("Bob", "person", tags=["outreach"])
        engine.add_relationship(ea, eb, "knows")
        packet = engine.compile_judgment_packet(["outreach"])
        assert len(packet["relationships"]) == 1

    def test_compile_includes_pending_outcomes(self, engine):
        engine.begin_cycle()
        kid = engine.add_knowledge("test", ["tag"])
        engine.add_pending_outcome("check later", [kid], check_after_cycles=0)
        packet = engine.compile_judgment_packet(["tag"])
        assert len(packet["pending_outcomes_due"]) == 1

    def test_compile_includes_recipe(self, engine):
        tid = engine.record_trajectory(
            steps=[{"s": 1}], outcome="ok", success=True, tags=["outreach"]
        )
        engine.compile_recipe(tid, "test_recipe", tags=["outreach"])
        packet = engine.compile_judgment_packet(["outreach"])
        assert packet["recipe"] is not None

    def test_compile_includes_cost_compression(self, engine):
        packet = engine.compile_judgment_packet([])
        assert "cost_compression" in packet


class TestCycleManagement:
    def test_begin_cycle_increments(self, engine):
        assert engine.begin_cycle() == 1
        assert engine.begin_cycle() == 2
        assert engine.begin_cycle() == 3

    def test_journal_entry(self, engine):
        engine.journal_entry(1, "test_event", {"detail": "value"})
        assert len(engine.data["journal"]) == 1
        assert engine.data["journal"][0]["event"] == "test_event"

    def test_journal_bounded(self, engine):
        for i in range(600):
            engine.journal_entry(i, f"event_{i}")
        assert len(engine.data["journal"]) == 500

    def test_stats(self, engine):
        engine.add_knowledge("k", ["t"])
        engine.add_warning("w", ["t"])
        engine.upsert_entity("E", "org")
        engine.add_directive("d")
        engine.begin_cycle()
        s = engine.stats()
        assert s["cycles"] == 1
        assert s["knowledge_entries"] == 1
        assert s["warnings"] == 1
        assert s["entities"] == 1
        assert s["directives"] == 1
        assert "recipes" in s
        assert "relationships" in s
        assert "pending_outcomes" in s
        assert "cost_compression" in s


class TestProofs:
    def test_record_proof(self, engine):
        pid = engine.record_proof(
            proof_type="delivery",
            description="Email sent successfully",
            artifact="msg-id-123",
        )
        assert len(engine.data["proofs"]) == 1
        assert engine.data["proofs"][0]["proof_type"] == "delivery"

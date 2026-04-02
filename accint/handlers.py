"""
AccInt Function Handlers — glue between the graph spec nodes and the state engine.

Each handler is a pure function: Dict[str, Any] → Dict[str, Any].
Side effects (state persistence) are explicit and go through StateEngine.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from accint.state_engine import StateEngine

# Singleton engine — path configurable via ACCINT_STATE_PATH env var
_ENGINE: Optional[StateEngine] = None


def _engine() -> StateEngine:
    global _ENGINE
    if _ENGINE is None:
        path = os.environ.get("ACCINT_STATE_PATH", "accint_state.json")
        _ENGINE = StateEngine(path)
    return _ENGINE


def set_engine(engine: StateEngine) -> None:
    """Allow external injection (for tests or custom runners)."""
    global _ENGINE
    _ENGINE = engine


# ── begin_cycle ──────────────────────────────────────────────

def begin_cycle(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Start a new AccInt cycle.  Increments the cycle counter."""
    engine = _engine()
    cycle = engine.begin_cycle()

    raw_input = inputs.get("input", {})
    domain = raw_input.get("domain", "general")
    objective = raw_input.get("objective", raw_input.get("text", ""))

    engine.journal_entry(cycle, "cycle_started", {
        "domain": domain,
        "objective": objective,
    })

    return {
        "cycle_number": cycle,
        "domain": domain,
        "objective": objective,
    }


# ── compile_judgment ─────────────────────────────────────────

def compile_judgment(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Compile a judgment packet from scored state for the current task."""
    engine = _engine()
    brief = inputs.get("brief", {})
    tags = brief.get("tags", [])

    packet = engine.compile_judgment_packet(task_tags=tags)

    engine.journal_entry(
        packet["cycle"],
        "judgment_compiled",
        {
            "knowledge_count": len(packet["knowledge"]),
            "warning_count": len(packet["warnings"]),
            "entity_count": len(packet["entities"]),
            "trajectory_count": len(packet["trajectories"]),
        },
    )

    return packet


# ── validate_receipt ─────────────────────────────────────────

def validate_receipt(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Validate that the strategist produced a proper citation receipt.

    The receipt must reference every knowledge and warning entry in the
    judgment packet — this is the retrieval-to-action binding enforcement.
    """
    output = inputs.get("strategist_output", {})
    packet = inputs.get("judgment_packet", {})

    receipt = output.get("receipt", {})
    if not receipt:
        return {"valid": False, "reason": "No receipt produced"}

    applied = {e.get("id") for e in receipt.get("applied", []) if isinstance(e, dict)}
    dismissed = {e.get("id") for e in receipt.get("dismissed", []) if isinstance(e, dict)}
    noted = {e.get("id") for e in receipt.get("noted", []) if isinstance(e, dict)}
    cited = applied | dismissed | noted

    # Check that all knowledge and warning entries are cited
    all_entries = []
    for entry in packet.get("knowledge", []):
        all_entries.append(entry.get("id"))
    for entry in packet.get("warnings", []):
        all_entries.append(entry.get("id"))

    missing = [eid for eid in all_entries if eid and eid not in cited]

    if missing:
        return {
            "valid": False,
            "reason": f"Receipt missing citations for {len(missing)} entries",
            "missing_ids": missing,
        }

    # Record usage for applied entries
    engine = _engine()
    for eid in applied:
        if eid:
            engine.record_usage(eid)

    return {"valid": True, "applied_count": len(applied), "total_cited": len(cited)}


# ── persist_knowledge ────────────────────────────────────────

def persist_knowledge(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Persist new knowledge, warnings, entities, trajectories, and outcomes."""
    engine = _engine()
    output = inputs.get("strategist_output", {})
    credit_assignments = inputs.get("credit_assignments", [])
    cycle = inputs.get("cycle_number", 0)

    knowledge_ids = []
    warning_ids = []

    # Store new knowledge
    for k in output.get("new_knowledge", []):
        if isinstance(k, dict) and k.get("content"):
            kid = engine.add_knowledge(
                content=k["content"],
                tags=k.get("tags", []),
                source_cycle=cycle,
                context=k.get("context"),
            )
            knowledge_ids.append(kid)

    # Store new warnings
    for w in output.get("new_warnings", []):
        if isinstance(w, dict) and w.get("content"):
            wid = engine.add_warning(
                content=w["content"],
                tags=w.get("tags", []),
                source_cycle=cycle,
                context=w.get("context"),
            )
            warning_ids.append(wid)

    # Entity updates
    for eu in output.get("entity_updates", []):
        if isinstance(eu, dict) and eu.get("name"):
            eid = engine.upsert_entity(
                name=eu["name"],
                entity_type=eu.get("type", "person"),
                attributes=eu.get("attributes"),
                tags=eu.get("tags"),
            )
            interaction = eu.get("interaction", {})
            if interaction:
                engine.record_entity_interaction(
                    entity_id=eid,
                    action=interaction.get("action", "updated"),
                    outcome=interaction.get("outcome"),
                    channel=interaction.get("channel"),
                    knowledge_refs=interaction.get("knowledge_refs", []),
                )

    # Outcome observations
    for obs in output.get("outcome_records", []):
        if isinstance(obs, dict) and obs.get("description"):
            engine.record_observed_outcome(
                description=obs["description"],
                related_entry_ids=obs.get("related_entry_ids", []),
                success=obs.get("success", False),
                evidence=obs.get("evidence"),
                cycle=cycle,
            )

    # Trajectories
    traj = output.get("trajectory")
    if isinstance(traj, dict) and traj.get("steps"):
        engine.record_trajectory(
            steps=traj["steps"],
            outcome=traj.get("outcome", ""),
            success=traj.get("success", False),
            tags=traj.get("tags", []),
            source_cycle=cycle,
        )

    # Apply credit assignments from scorer
    if isinstance(credit_assignments, list):
        for ca in credit_assignments:
            if isinstance(ca, dict) and ca.get("entry_id"):
                engine.record_outcome(
                    entry_id=ca["entry_id"],
                    success=ca.get("success", False),
                    weight=ca.get("weight", 1.0),
                )

    engine.journal_entry(cycle, "knowledge_persisted", {
        "new_knowledge": len(knowledge_ids),
        "new_warnings": len(warning_ids),
        "credit_assignments": len(credit_assignments) if isinstance(credit_assignments, list) else 0,
    })

    return {
        "knowledge_ids": knowledge_ids,
        "warning_ids": warning_ids,
    }


# ── check_self_improvement ───────────────────────────────────

def check_self_improvement(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Constitutional gate for self-improvement proposals.

    In this implementation, improvements are logged but require
    owner approval (governance constraint).  The system cannot
    weaken its own constraints.
    """
    engine = _engine()
    output = inputs.get("strategist_output", {})
    cycle = inputs.get("cycle_number", 0)

    # Check if strategist proposed any improvements
    plan = output.get("plan", {})
    improvements = plan.get("proposed_improvements", [])

    if not improvements:
        return {"has_proposals": False, "proposals": []}

    # Log proposals — they require owner review
    results = []
    for imp in improvements:
        if isinstance(imp, dict):
            result = {
                "proposal": imp.get("description", ""),
                "approved": False,
                "reason": "Requires owner approval (constitutional gate)",
                "risk_level": "medium",
            }
            results.append(result)

            # Record as warning so it's tracked
            engine.add_warning(
                content=f"Pending improvement proposal: {imp.get('description', '')}",
                tags=["self-improvement", "pending-review"],
                source_cycle=cycle,
            )

    engine.journal_entry(cycle, "self_improvement_checked", {
        "proposals": len(improvements),
        "approved": 0,
    })

    return {"has_proposals": True, "proposals": results}


# ── close_cycle ──────────────────────────────────────────────

def close_cycle(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Close the current AccInt cycle and produce a summary."""
    engine = _engine()
    cycle = inputs.get("cycle_number", 0)
    domain = inputs.get("domain", "unknown")
    output = inputs.get("strategist_output", {})
    knowledge_ids = inputs.get("new_knowledge_ids", [])
    warning_ids = inputs.get("new_warning_ids", [])
    credit_assignments = inputs.get("credit_assignments", [])
    governance = inputs.get("governance_check", {})

    summary = {
        "cycle": cycle,
        "domain": domain,
        "knowledge_deposited": len(knowledge_ids) if knowledge_ids else 0,
        "warnings_deposited": len(warning_ids) if warning_ids else 0,
        "credit_assignments": len(credit_assignments) if isinstance(credit_assignments, list) else 0,
        "self_improvement_proposals": len(governance.get("proposals", [])) if governance else 0,
        "plan_summary": output.get("plan", {}).get("objective", ""),
        "stats": engine.stats(),
    }

    engine.journal_entry(cycle, "cycle_closed", summary)

    return summary

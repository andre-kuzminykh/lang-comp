#!/usr/bin/env python3
"""
AccInt Demo — Simulates a multi-cycle outreach scenario.

Shows how the system accretes judgment through repeated contact with reality:
- Knowledge accumulates and gets scored
- Warnings prevent repeated mistakes
- Entities build interaction history
- Trajectories become recipes
- Pending outcomes resolve with delayed credit assignment
- Cost compression improves as recipes accrete

Run:  python demo_accint.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from comp import GraphSpecCompiler, LocalRegistry, load_spec
from accint.state_engine import StateEngine
from accint.scoring import BetaScore
from accint.handlers import set_engine


# ── Demo LLM — simulates realistic multi-cycle scenario ──────

CYCLE_SCRIPTS = [
    # Cycle 1: Initial research
    {
        "brief": {
            "title": "Research premium retail stores in Moscow",
            "domain": "outreach",
            "objective": "Find retail stores that might carry premium skincare line",
            "tags": ["outreach", "retail", "moscow"],
            "constraints": ["Premium segment only", "Must have physical location"],
            "relevant_entities": [],
            "urgency": "normal",
            "success_criteria": ["5+ candidate stores identified"],
        },
        "strategist": {
            "receipt": {"applied": [], "dismissed": [], "noted": []},
            "plan": {
                "objective": "Research premium retail stores in Moscow",
                "steps": [
                    "Search for premium beauty/skincare retailers",
                    "Verify physical locations and social media presence",
                    "Score by brand alignment and accessibility",
                ],
            },
            "actions": [{"action": "web_research", "target": "moscow premium retail"}],
            "observations": ["Found 6 candidate stores with strong social media presence"],
            "new_knowledge": [
                {
                    "content": "Instagram DMs get faster response from Moscow boutiques than email (3 out of 4 responded within 24h)",
                    "tags": ["outreach", "retail", "moscow", "channel"],
                },
                {
                    "content": "Premium Moscow boutiques prefer seeing product photos before pricing discussion",
                    "tags": ["outreach", "retail", "moscow", "approach"],
                },
            ],
            "new_warnings": [],
            "entity_updates": [
                {
                    "name": "Cosmotheca",
                    "type": "org",
                    "attributes": {"sector": "premium beauty", "location": "Moscow", "ig_followers": 45000},
                    "tags": ["outreach", "retail", "moscow"],
                    "interaction": {"action": "researched", "outcome": "strong candidate", "channel": "web"},
                },
                {
                    "name": "Articoli",
                    "type": "org",
                    "attributes": {"sector": "niche perfumery", "location": "Moscow", "ig_followers": 28000},
                    "tags": ["outreach", "retail", "moscow"],
                    "interaction": {"action": "researched", "outcome": "strong candidate", "channel": "web"},
                },
                {
                    "name": "Rivoli Perfumery",
                    "type": "org",
                    "attributes": {"sector": "luxury beauty", "location": "Moscow", "ig_followers": 62000},
                    "tags": ["outreach", "retail", "moscow"],
                    "interaction": {"action": "researched", "outcome": "possible match", "channel": "web"},
                },
            ],
            "outcome_records": [],
            "pending_outcomes": [],
            "trajectory": {
                "steps": [
                    {"step": "web_search", "query": "premium skincare retail moscow"},
                    {"step": "ig_profile_check", "count": 6},
                    {"step": "shortlist", "result": "3 strong, 3 possible"},
                ],
                "outcome": "6 candidates identified, 3 strong",
                "success": True,
                "tags": ["outreach", "retail", "research"],
            },
        },
    },
    # Cycle 2: First outreach via Instagram
    {
        "brief": {
            "title": "Outreach to Cosmotheca via Instagram DM",
            "domain": "outreach",
            "objective": "Send initial message to Cosmotheca with product photos",
            "tags": ["outreach", "retail", "moscow", "instagram"],
            "constraints": ["Lead with product photos", "Warm tone"],
            "relevant_entities": ["Cosmotheca"],
            "urgency": "normal",
            "success_criteria": ["Message delivered", "Response within 48h"],
        },
        "strategist": {
            "receipt": {"applied": [], "dismissed": [], "noted": []},
            "plan": {
                "objective": "Send warm DM to Cosmotheca with product photos",
                "steps": [
                    "Prepare product photo carousel",
                    "Draft warm intro message (no pricing yet — per scored knowledge)",
                    "Send via Instagram DM",
                    "Record delivery proof",
                ],
            },
            "actions": [
                {"action": "ig_send_dm", "target": "Cosmotheca", "status": "delivered"},
            ],
            "observations": ["Message delivered. Cosmotheca viewed within 2 hours."],
            "new_knowledge": [
                {
                    "content": "Cosmotheca buyer views DMs quickly — high engagement signal",
                    "tags": ["outreach", "retail", "moscow", "cosmotheca"],
                },
            ],
            "new_warnings": [],
            "entity_updates": [
                {
                    "name": "Cosmotheca",
                    "type": "org",
                    "attributes": {"response_speed": "fast", "engagement": "high"},
                    "tags": ["outreach", "retail", "moscow"],
                    "interaction": {
                        "action": "ig_dm_sent",
                        "outcome": "viewed_2h",
                        "channel": "instagram",
                    },
                },
            ],
            "outcome_records": [],
            "pending_outcomes": [
                {
                    "description": "Check if Cosmotheca replied to Instagram DM",
                    "related_entry_ids": [],  # Will be filled dynamically
                    "check_after_cycles": 2,
                },
            ],
            "trajectory": {
                "steps": [
                    {"step": "prepare_photos", "count": 4},
                    {"step": "draft_warm_dm", "tone": "friendly_professional"},
                    {"step": "ig_send_dm", "target": "cosmotheca"},
                    {"step": "verify_delivery", "result": "viewed"},
                ],
                "outcome": "DM delivered and viewed within 2 hours",
                "success": True,
                "tags": ["outreach", "instagram", "dm"],
            },
        },
    },
    # Cycle 3: Outreach to Articoli — cold email (will fail)
    {
        "brief": {
            "title": "Outreach to Articoli via cold email",
            "domain": "outreach",
            "objective": "Send cold email to Articoli with product info",
            "tags": ["outreach", "retail", "moscow", "email"],
            "constraints": [],
            "relevant_entities": ["Articoli"],
            "urgency": "normal",
            "success_criteria": ["Email delivered"],
        },
        "strategist": {
            "receipt": {"applied": [], "dismissed": [], "noted": []},
            "plan": {
                "objective": "Email Articoli with product catalog",
                "steps": ["Draft formal email", "Attach catalog PDF", "Send"],
            },
            "actions": [
                {"action": "email_sent", "target": "Articoli", "status": "bounced"},
            ],
            "observations": ["Email bounced — no public email address found. Instagram shows 'DM for business inquiries'."],
            "new_knowledge": [],
            "new_warnings": [
                {
                    "content": "Articoli has no public email — cold email approach fails. Must use Instagram DM instead.",
                    "tags": ["outreach", "retail", "moscow", "articoli", "email"],
                },
                {
                    "content": "Moscow niche boutiques often have no public email; Instagram DM is the primary business channel",
                    "tags": ["outreach", "retail", "moscow", "channel"],
                },
            ],
            "entity_updates": [
                {
                    "name": "Articoli",
                    "type": "org",
                    "attributes": {"email_available": False, "preferred_channel": "instagram"},
                    "tags": ["outreach", "retail", "moscow"],
                    "interaction": {
                        "action": "email_attempt",
                        "outcome": "bounced",
                        "channel": "email",
                    },
                },
            ],
            "outcome_records": [
                {
                    "description": "Cold email to Articoli bounced — no valid email address",
                    "related_entry_ids": [],
                    "success": False,
                    "evidence": "SMTP bounce: address not found",
                },
            ],
            "pending_outcomes": [],
            "trajectory": {
                "steps": [
                    {"step": "draft_email", "tone": "formal"},
                    {"step": "send_email", "target": "articoli"},
                    {"step": "delivery_check", "result": "bounced"},
                ],
                "outcome": "Email bounced, approach failed",
                "success": False,
                "tags": ["outreach", "email", "failure"],
            },
        },
    },
    # Cycle 4: Cosmotheca replies! + Articoli via IG (learning from failure)
    {
        "brief": {
            "title": "Follow up with Cosmotheca reply + contact Articoli via IG",
            "domain": "outreach",
            "objective": "Handle Cosmotheca reply and re-approach Articoli via correct channel",
            "tags": ["outreach", "retail", "moscow", "instagram"],
            "constraints": ["Use Instagram for Articoli (email failed)"],
            "relevant_entities": ["Cosmotheca", "Articoli"],
            "urgency": "high",
            "success_criteria": ["Reply to Cosmotheca", "Articoli DM sent"],
        },
        "strategist": {
            "receipt": {"applied": [], "dismissed": [], "noted": []},
            "plan": {
                "objective": "Respond to Cosmotheca + DM Articoli",
                "steps": [
                    "Read Cosmotheca reply and respond with pricing",
                    "Apply Instagram DM approach to Articoli (learned from prior failure)",
                ],
            },
            "actions": [
                {"action": "ig_reply", "target": "Cosmotheca", "status": "sent"},
                {"action": "ig_send_dm", "target": "Articoli", "status": "delivered"},
            ],
            "observations": [
                "Cosmotheca asked about pricing and MOQ — strong buying signal!",
                "Articoli DM delivered — product photos approach (from scored knowledge)",
            ],
            "new_knowledge": [
                {
                    "content": "Cosmotheca moved to pricing discussion after product photos — the photos-first approach works for premium Moscow boutiques",
                    "tags": ["outreach", "retail", "moscow", "approach", "validation"],
                },
                {
                    "content": "Instagram DM with product photos is the universal outreach channel for Moscow boutiques — even when email seems available, IG DM is preferred",
                    "tags": ["outreach", "retail", "moscow", "channel", "validated"],
                },
            ],
            "new_warnings": [],
            "entity_updates": [
                {
                    "name": "Cosmotheca",
                    "type": "org",
                    "attributes": {"buying_signal": True, "stage": "pricing_discussion"},
                    "tags": ["outreach", "retail", "moscow"],
                    "interaction": {
                        "action": "ig_reply_pricing",
                        "outcome": "pricing_requested",
                        "channel": "instagram",
                    },
                },
                {
                    "name": "Articoli",
                    "type": "org",
                    "attributes": {},
                    "tags": ["outreach", "retail", "moscow"],
                    "interaction": {
                        "action": "ig_dm_sent",
                        "outcome": "delivered",
                        "channel": "instagram",
                    },
                },
            ],
            "outcome_records": [
                {
                    "description": "Instagram DM + product photos approach produced a buying signal from Cosmotheca",
                    "related_entry_ids": [],  # Will reference knowledge about IG DMs
                    "success": True,
                    "evidence": "Cosmotheca asked about pricing and MOQ",
                },
            ],
            "pending_outcomes": [
                {
                    "description": "Check if Articoli responds to Instagram DM (photos-first approach)",
                    "related_entry_ids": [],
                    "check_after_cycles": 2,
                },
                {
                    "description": "Check if Cosmotheca proceeds to order after pricing discussion",
                    "related_entry_ids": [],
                    "check_after_cycles": 5,
                },
            ],
            "trajectory": {
                "steps": [
                    {"step": "read_cosmotheca_reply", "signal": "buying_interest"},
                    {"step": "send_pricing_info", "target": "cosmotheca"},
                    {"step": "prepare_photos_for_articoli"},
                    {"step": "ig_send_dm", "target": "articoli"},
                ],
                "outcome": "Cosmotheca progressed to pricing; Articoli contacted via correct channel",
                "success": True,
                "tags": ["outreach", "instagram", "multi-entity"],
            },
        },
    },
    # Cycle 5: System has learned — uses accumulated judgment automatically
    {
        "brief": {
            "title": "Outreach to Rivoli Perfumery",
            "domain": "outreach",
            "objective": "Contact Rivoli using accumulated outreach playbook",
            "tags": ["outreach", "retail", "moscow", "instagram"],
            "constraints": ["Use Instagram DM (validated channel)", "Photos first, pricing later"],
            "relevant_entities": ["Rivoli Perfumery"],
            "urgency": "normal",
            "success_criteria": ["DM delivered and viewed"],
        },
        "strategist": {
            "receipt": {"applied": [], "dismissed": [], "noted": []},
            "plan": {
                "objective": "Apply validated playbook to Rivoli",
                "approach": "Using accumulated judgment: IG DM + product photos + warm tone",
                "steps": [
                    "Apply validated IG DM recipe (from trajectory scoring)",
                    "Send product photos with warm intro",
                    "No pricing in first message (per scored knowledge)",
                ],
            },
            "actions": [
                {"action": "ig_send_dm", "target": "Rivoli Perfumery", "status": "delivered"},
            ],
            "observations": [
                "Applied Tier 0 recipe from prior Instagram DM trajectory. Execution cost reduced.",
                "Rivoli viewed DM within 30 minutes — fastest response so far.",
            ],
            "new_knowledge": [
                {
                    "content": "The IG DM + photos playbook now has 3/3 successful deliveries across Moscow premium boutiques — high confidence",
                    "tags": ["outreach", "retail", "moscow", "playbook", "validated"],
                },
            ],
            "new_warnings": [],
            "entity_updates": [
                {
                    "name": "Rivoli Perfumery",
                    "type": "org",
                    "attributes": {"response_speed": "very fast", "engagement": "high"},
                    "tags": ["outreach", "retail", "moscow"],
                    "interaction": {
                        "action": "ig_dm_sent",
                        "outcome": "viewed_30min",
                        "channel": "instagram",
                    },
                },
            ],
            "outcome_records": [
                {
                    "description": "IG DM playbook successful on 3rd store (Rivoli) — playbook validated",
                    "related_entry_ids": [],
                    "success": True,
                    "evidence": "DM viewed within 30 minutes",
                },
            ],
            "pending_outcomes": [
                {
                    "description": "Check if Rivoli replies to DM",
                    "related_entry_ids": [],
                    "check_after_cycles": 2,
                },
            ],
            "trajectory": {
                "steps": [
                    {"step": "load_ig_dm_recipe"},
                    {"step": "prepare_photos", "count": 4},
                    {"step": "ig_send_dm", "target": "rivoli_perfumery"},
                    {"step": "verify_delivery", "result": "viewed_30min"},
                ],
                "outcome": "Recipe replay successful — playbook validated on 3rd entity",
                "success": True,
                "tags": ["outreach", "instagram", "dm", "recipe_replay"],
            },
        },
    },
]

_cycle_idx = 0


def demo_llm_runner(config, inputs):
    """LLM runner that replays the demo scenario script."""
    global _cycle_idx
    system = config.get("system_prompt", "")

    if _cycle_idx >= len(CYCLE_SCRIPTS):
        script = CYCLE_SCRIPTS[-1]  # Reuse last
    else:
        script = CYCLE_SCRIPTS[_cycle_idx]

    if "Brief Generator" in system or "structured brief" in system:
        return script["brief"]
    elif "Strategist" in system:
        strat = script["strategist"]
        # Dynamically fill receipt with actual knowledge/warning IDs from packet
        packet = inputs.get("judgment_packet", {})
        if isinstance(packet, dict):
            knowledge = packet.get("knowledge", [])
            warnings = packet.get("warnings", [])
            applied = []
            for k in knowledge:
                if isinstance(k, dict) and k.get("id"):
                    applied.append({"id": k["id"], "reason": "Consulted accumulated knowledge"})
            for w in warnings:
                if isinstance(w, dict) and w.get("id"):
                    applied.append({"id": w["id"], "reason": "Warning acknowledged — adjusting approach"})
            strat["receipt"]["applied"] = applied
        return strat
    elif "Scorer" in system or "credit" in system:
        return {"assignments": []}
    else:
        return {"stub": True}


def demo_cycle_hook():
    """Called after each cycle — advances the script."""
    global _cycle_idx
    _cycle_idx += 1


# ── Main demo ────────────────────────────────────────────────

def main():
    state_path = "/tmp/accint_demo_state.json"
    # Clean start
    if os.path.exists(state_path):
        os.remove(state_path)

    engine = StateEngine(state_path)
    set_engine(engine)

    # Add owner directive
    engine.add_directive(
        "Find premium retail stores in Moscow for skincare line placement. "
        "Use Instagram DM as primary channel. Lead with product photos."
    )

    # Build graph
    registry = LocalRegistry()
    registry.register_llm_runner("demo_llm", demo_llm_runner)
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

    spec = load_spec(Path(__file__).parent / "accint" / "accint_graph.json")
    compiler = GraphSpecCompiler(registry, default_llm_runner="demo_llm")
    graph = compiler.compile_spec(spec)

    print("=" * 70)
    print("  AccInt Demo — Premium Retail Outreach in Moscow")
    print("  Simulating 5 cycles of accreted intelligence")
    print("=" * 70)

    for i in range(5):
        script = CYCLE_SCRIPTS[i]
        print(f"\n{'─' * 70}")
        print(f"  CYCLE {i + 1}: {script['brief']['title']}")
        print(f"{'─' * 70}")

        payload = {
            "input": {
                "text": script["brief"]["objective"],
                "domain": "outreach",
                "objective": script["brief"]["objective"],
            }
        }
        config = {"configurable": {"thread_id": f"demo-{i + 1}"}}

        result = graph.invoke(payload, config=config)
        demo_cycle_hook()

        summary = result.get("cycle_summary", {})
        stats = summary.get("stats", {})

        print(f"\n  Results:")
        print(f"    Knowledge deposited:  +{summary.get('knowledge_deposited', 0)}")
        print(f"    Warnings deposited:   +{summary.get('warnings_deposited', 0)}")

        print(f"\n  Accumulated state:")
        print(f"    Total knowledge:      {stats.get('knowledge_entries', 0)}")
        print(f"    Total warnings:       {stats.get('warnings', 0)}")
        print(f"    Entities tracked:     {stats.get('entities', 0)}")
        print(f"    Trajectories:         {stats.get('trajectories', 0)}")
        print(f"    Recipes compiled:     {stats.get('recipes', 0)}")
        print(f"    Relationships:        {stats.get('relationships', 0)}")
        print(f"    Pending outcomes:     {stats.get('pending_outcomes', 0)}")

    # ── Final analysis ────────────────────────────────────────

    print(f"\n{'=' * 70}")
    print("  FINAL ANALYSIS — What the system accreted")
    print(f"{'=' * 70}")

    stats = engine.stats()
    print(f"\n  State summary after {stats['cycles']} cycles:")
    for key, value in stats.items():
        print(f"    {key:25s} {value}")

    print(f"\n  Knowledge entries (scored):")
    for k in engine.data["knowledge"]:
        bs = BetaScore.from_dict(k["score"])
        print(f"    [{bs.mean:.2f} conf={bs.confidence:.2f}] {k['content'][:80]}")

    if engine.data["warnings"]:
        print(f"\n  Warnings (negative experience):")
        for w in engine.data["warnings"]:
            bs = BetaScore.from_dict(w["score"])
            print(f"    [!] {w['content'][:80]}")

    print(f"\n  Entities:")
    for ent in engine.data["entities"]:
        interactions = len(ent.get("interactions", []))
        print(f"    {ent['name']:20s}  type={ent['type']:6s}  interactions={interactions}  attrs={json.dumps(ent['attributes'], ensure_ascii=False)[:60]}")

    if engine.data.get("recipes"):
        print(f"\n  Recipes (replayable procedures):")
        for r in engine.data["recipes"]:
            bs = BetaScore.from_dict(r["score"])
            print(f"    [{r['status']:10s} score={bs.mean:.2f}] {r['name']}  ({len(r['steps'])} steps)")

    pending = [p for p in engine.data.get("pending_outcomes", []) if not p.get("resolved")]
    if pending:
        print(f"\n  Pending outcomes (delayed credit assignment):")
        for p in pending:
            print(f"    [cycle {p.get('check_after_cycle', '?')}] {p['description'][:70]}")

    print(f"\n  Key insight: The system started cycle 1 with ZERO knowledge.")
    print(f"  By cycle 5, it had {stats['knowledge_entries']} scored insights, {stats['warnings']} warnings,")
    print(f"  {stats['entities']} entity models, and {stats.get('recipes', 0)} replayable recipes.")
    print(f"  Each cycle read and built on the judgment of all prior cycles.")
    print(f"\n  This is accreted intelligence: judgment that compounds through")
    print(f"  contact with reality, not through retraining.")

    # Cleanup
    os.remove(state_path)


if __name__ == "__main__":
    main()

"""
AccInt State Engine — scored external state that persists across sessions.

The engine is deliberately unintelligent: it validates, stores, and retrieves,
but never decides.  All intelligence lives in the AI models and in the scored
knowledge.  Safety checks exist outside the code they protect.

Persists to a single JSON file so the substrate outlives any session or model.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from accint.scoring import BetaScore, decay_confidence, rank_entries, thompson_sample


# ── Entry types ──────────────────────────────────────────────

ENTRY_KINDS = {
    "knowledge",   # positive insight / approach
    "warning",     # negative experience — what failed and why
    "directive",   # owner intent / constraint
    "entity",      # person, org, platform model
    "trajectory",  # sequence of steps that produced an outcome
    "outcome",     # recorded observation of a result
    "proof",       # evidence artifact (delivery proof, identity verification)
}


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> float:
    return time.time()


# ── State Engine ─────────────────────────────────────────────

class StateEngine:
    """JSON-file-backed scored state store.

    All mutations go through this class.  The model never touches
    the file directly — governance is structural.
    """

    def __init__(self, path: str | Path = "accint_state.json"):
        self.path = Path(path)
        self.data: Dict[str, Any] = self._load()

    # ── persistence ──────────────────────────────────────────

    def _load(self) -> Dict[str, Any]:
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        return self._empty_state()

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        tmp.replace(self.path)

    @staticmethod
    def _empty_state() -> Dict[str, Any]:
        return {
            "version": 1,
            "created": _now(),
            "owner_directives": [],
            "knowledge": [],
            "warnings": [],
            "entities": [],
            "trajectories": [],
            "outcomes": [],
            "proofs": [],
            "governance": {
                "constitutional_gates": [
                    "No self-modification of governance rules without owner approval",
                    "All improvements require measured evidence of benefit",
                    "Failed proposals become scored warnings",
                    "Owner can override any directive",
                ],
                "max_auto_iterations": 20,
            },
            "pending_outcomes": [],
            "recipes": [],
            "relationships": [],
            "cost_tiers": {
                "tier_0_cached": 0,
                "tier_1_semantic": 0,
                "tier_2_visual": 0,
                "tier_3_reasoning": 0,
            },
            "cycle_count": 0,
            "journal": [],
        }

    # ── knowledge CRUD ───────────────────────────────────────

    def add_knowledge(
        self,
        content: str,
        tags: List[str],
        *,
        kind: str = "knowledge",
        source_cycle: Optional[int] = None,
        context: Optional[str] = None,
    ) -> str:
        if kind not in ENTRY_KINDS:
            raise ValueError(f"Unknown entry kind: {kind}")

        entry_id = _new_id()
        entry = {
            "id": entry_id,
            "kind": kind,
            "content": content,
            "tags": tags,
            "context": context,
            "score": BetaScore(last_updated=_now()).to_dict(),
            "created": _now(),
            "source_cycle": source_cycle,
        }

        bucket = "warnings" if kind == "warning" else "knowledge"
        self.data[bucket].append(entry)
        self.save()
        return entry_id

    def add_warning(
        self, content: str, tags: List[str], **kwargs
    ) -> str:
        return self.add_knowledge(content, tags, kind="warning", **kwargs)

    def _find_entry(self, entry_id: str) -> Optional[Dict[str, Any]]:
        for bucket in ("knowledge", "warnings"):
            for entry in self.data[bucket]:
                if entry["id"] == entry_id:
                    return entry
        return None

    def record_usage(self, entry_id: str) -> None:
        entry = self._find_entry(entry_id)
        if entry:
            bs = BetaScore.from_dict(entry["score"])
            bs.record_usage()
            entry["score"] = bs.to_dict()
            self.save()

    def record_outcome(
        self, entry_id: str, success: bool, weight: float = 1.0
    ) -> None:
        entry = self._find_entry(entry_id)
        if entry:
            bs = BetaScore.from_dict(entry["score"])
            if success:
                bs.record_success(weight)
            else:
                bs.record_failure(weight)
            entry["score"] = bs.to_dict()
            self.save()

    # ── entity tracking ──────────────────────────────────────

    def upsert_entity(
        self,
        name: str,
        entity_type: str = "person",
        attributes: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> str:
        for ent in self.data["entities"]:
            if ent["name"].lower() == name.lower():
                if attributes:
                    ent["attributes"].update(attributes)
                if tags:
                    ent["tags"] = list(set(ent.get("tags", []) + tags))
                ent["updated"] = _now()
                self.save()
                return ent["id"]

        eid = _new_id()
        self.data["entities"].append({
            "id": eid,
            "name": name,
            "type": entity_type,
            "attributes": attributes or {},
            "tags": tags or [],
            "interactions": [],
            "score": BetaScore(last_updated=_now()).to_dict(),
            "created": _now(),
            "updated": _now(),
        })
        self.save()
        return eid

    def record_entity_interaction(
        self,
        entity_id: str,
        action: str,
        outcome: Optional[str] = None,
        channel: Optional[str] = None,
        knowledge_refs: Optional[List[str]] = None,
    ) -> None:
        for ent in self.data["entities"]:
            if ent["id"] == entity_id:
                ent["interactions"].append({
                    "action": action,
                    "outcome": outcome,
                    "channel": channel,
                    "knowledge_refs": knowledge_refs or [],
                    "timestamp": _now(),
                })
                ent["updated"] = _now()
                self.save()
                return

    # ── trajectory learning ──────────────────────────────────

    def record_trajectory(
        self,
        steps: List[Dict[str, Any]],
        outcome: str,
        success: bool,
        tags: Optional[List[str]] = None,
        source_cycle: Optional[int] = None,
    ) -> str:
        tid = _new_id()
        self.data["trajectories"].append({
            "id": tid,
            "steps": steps,
            "outcome": outcome,
            "success": success,
            "tags": tags or [],
            "score": BetaScore(
                alpha=2.0 if success else 1.0,
                beta=1.0 if success else 2.0,
                last_updated=_now(),
            ).to_dict(),
            "created": _now(),
            "source_cycle": source_cycle,
        })
        self.save()
        return tid

    # ── outcome observation ──────────────────────────────────

    def record_observed_outcome(
        self,
        description: str,
        related_entry_ids: List[str],
        success: bool,
        evidence: Optional[str] = None,
        cycle: Optional[int] = None,
    ) -> str:
        oid = _new_id()
        self.data["outcomes"].append({
            "id": oid,
            "description": description,
            "related_entries": related_entry_ids,
            "success": success,
            "evidence": evidence,
            "cycle": cycle,
            "timestamp": _now(),
        })
        # Credit assignment: propagate outcome to related knowledge
        for eid in related_entry_ids:
            self.record_outcome(eid, success)
        self.save()
        return oid

    # ── proof management ─────────────────────────────────────

    def record_proof(
        self,
        proof_type: str,
        description: str,
        artifact: Optional[str] = None,
        related_entity: Optional[str] = None,
    ) -> str:
        pid = _new_id()
        self.data["proofs"].append({
            "id": pid,
            "proof_type": proof_type,  # "identity" | "delivery" | "outcome"
            "description": description,
            "artifact": artifact,
            "related_entity": related_entity,
            "timestamp": _now(),
        })
        self.save()
        return pid

    # ── pending outcomes (delayed credit assignment) ──────────

    def add_pending_outcome(
        self,
        description: str,
        related_entry_ids: List[str],
        check_after_cycles: int = 5,
        source_cycle: Optional[int] = None,
    ) -> str:
        """Record an outcome that can only be observed later.

        The system will re-check after `check_after_cycles` cycles.
        This solves delayed credit assignment: a partnership approach
        tried today may only show results weeks later.
        """
        pid = _new_id()
        current_cycle = self.data["cycle_count"]
        self.data["pending_outcomes"].append({
            "id": pid,
            "description": description,
            "related_entry_ids": related_entry_ids,
            "check_after_cycle": current_cycle + check_after_cycles,
            "source_cycle": source_cycle or current_cycle,
            "created": _now(),
            "resolved": False,
            "resolution": None,
        })
        self.save()
        return pid

    def get_due_pending_outcomes(self) -> List[Dict[str, Any]]:
        """Return pending outcomes that are due for checking."""
        current_cycle = self.data["cycle_count"]
        return [
            po for po in self.data["pending_outcomes"]
            if not po.get("resolved") and po.get("check_after_cycle", 0) <= current_cycle
        ]

    def resolve_pending_outcome(
        self, pending_id: str, success: bool, evidence: Optional[str] = None
    ) -> None:
        """Resolve a pending outcome and propagate credit to related entries."""
        for po in self.data["pending_outcomes"]:
            if po["id"] == pending_id and not po.get("resolved"):
                po["resolved"] = True
                po["resolution"] = {
                    "success": success,
                    "evidence": evidence,
                    "resolved_at": _now(),
                    "resolved_cycle": self.data["cycle_count"],
                }
                # Credit assignment
                for eid in po.get("related_entry_ids", []):
                    self.record_outcome(eid, success)
                # Also record as a full outcome
                self.record_observed_outcome(
                    description=f"[Resolved pending] {po['description']}",
                    related_entry_ids=po.get("related_entry_ids", []),
                    success=success,
                    evidence=evidence,
                    cycle=self.data["cycle_count"],
                )
                self.save()
                return

    # ── recipes (successful traces → replayable procedures) ──

    def compile_recipe(
        self,
        trajectory_id: str,
        name: str,
        tags: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Promote a successful trajectory into a replayable recipe.

        Only successful trajectories with sufficient confidence can become
        recipes.  Recipes are scored separately and can be quarantined
        if their performance degrades.
        """
        traj = None
        for t in self.data["trajectories"]:
            if t["id"] == trajectory_id:
                traj = t
                break
        if not traj or not traj.get("success"):
            return None

        rid = _new_id()
        self.data["recipes"].append({
            "id": rid,
            "name": name,
            "source_trajectory": trajectory_id,
            "steps": traj["steps"],
            "tags": tags or traj.get("tags", []),
            "score": BetaScore(alpha=2.0, beta=1.0, last_updated=_now()).to_dict(),
            "status": "active",  # active | quarantined
            "created": _now(),
            "replay_count": 0,
        })
        self.save()
        return rid

    def get_recipe(self, tags: List[str]) -> Optional[Dict[str, Any]]:
        """Find the best active recipe matching the given tags (Thompson sampling)."""
        candidates = [
            r for r in self.data["recipes"]
            if r.get("status") == "active"
            and len(set(r.get("tags", [])) & set(tags)) > 0
        ]
        if not candidates:
            return None
        ranked = rank_entries(candidates, top_k=1)
        return ranked[0] if ranked else None

    def record_recipe_outcome(self, recipe_id: str, success: bool) -> None:
        """Score a recipe replay.  Quarantine if score drops below threshold."""
        for r in self.data["recipes"]:
            if r["id"] == recipe_id:
                bs = BetaScore.from_dict(r["score"])
                if success:
                    bs.record_success()
                else:
                    bs.record_failure()
                r["score"] = bs.to_dict()
                r["replay_count"] = r.get("replay_count", 0) + 1
                # Quarantine if mean drops below 0.3 with enough evidence
                if bs.mean < 0.3 and bs.evidence >= 5:
                    r["status"] = "quarantined"
                self.save()
                return

    # ── relationships (entity-to-entity scored edges) ────────

    def add_relationship(
        self,
        entity_a_id: str,
        entity_b_id: str,
        relation_type: str = "knows",
        attributes: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> str:
        """Create or update a scored edge between two entities."""
        # Check for existing relationship
        for rel in self.data["relationships"]:
            if (
                (rel["entity_a"] == entity_a_id and rel["entity_b"] == entity_b_id)
                or (rel["entity_a"] == entity_b_id and rel["entity_b"] == entity_a_id)
            ) and rel["relation_type"] == relation_type:
                if attributes:
                    rel["attributes"].update(attributes)
                if tags:
                    rel["tags"] = list(set(rel.get("tags", []) + tags))
                rel["updated"] = _now()
                self.save()
                return rel["id"]

        rid = _new_id()
        self.data["relationships"].append({
            "id": rid,
            "entity_a": entity_a_id,
            "entity_b": entity_b_id,
            "relation_type": relation_type,
            "attributes": attributes or {},
            "tags": tags or [],
            "score": BetaScore(last_updated=_now()).to_dict(),
            "created": _now(),
            "updated": _now(),
        })
        self.save()
        return rid

    def get_entity_relationships(self, entity_id: str) -> List[Dict[str, Any]]:
        """Get all relationships for an entity."""
        return [
            r for r in self.data["relationships"]
            if r["entity_a"] == entity_id or r["entity_b"] == entity_id
        ]

    def record_relationship_outcome(
        self, relationship_id: str, success: bool
    ) -> None:
        """Score a relationship interaction."""
        for rel in self.data["relationships"]:
            if rel["id"] == relationship_id:
                bs = BetaScore.from_dict(rel["score"])
                if success:
                    bs.record_success()
                else:
                    bs.record_failure()
                rel["score"] = bs.to_dict()
                self.save()
                return

    # ── cost tiers (execution cost tracking) ─────────────────

    def record_execution_tier(self, tier: int) -> None:
        """Record which cost tier was used for an execution step.

        Tier 0: Cached recipe replay (cheapest)
        Tier 1: Semantic recovery (selector-based)
        Tier 2: Visual grounding (screenshot-based)
        Tier 3: Full HIDL reasoning (most expensive)
        """
        tier_keys = {
            0: "tier_0_cached",
            1: "tier_1_semantic",
            2: "tier_2_visual",
            3: "tier_3_reasoning",
        }
        key = tier_keys.get(tier)
        if key:
            self.data["cost_tiers"][key] = self.data["cost_tiers"].get(key, 0) + 1
            self.save()

    def get_cost_distribution(self) -> Dict[str, int]:
        """Return the distribution of execution across cost tiers."""
        return dict(self.data.get("cost_tiers", {}))

    def get_cost_compression_ratio(self) -> float:
        """Ratio of cheap executions (tier 0-1) to expensive (tier 2-3).

        Higher = more accreted (more work replays cheaply).
        """
        tiers = self.data.get("cost_tiers", {})
        cheap = tiers.get("tier_0_cached", 0) + tiers.get("tier_1_semantic", 0)
        expensive = tiers.get("tier_2_visual", 0) + tiers.get("tier_3_reasoning", 0)
        if expensive == 0:
            return float("inf") if cheap > 0 else 0.0
        return cheap / expensive

    # ── owner directives ─────────────────────────────────────

    def add_directive(self, content: str, priority: int = 0) -> str:
        did = _new_id()
        self.data["owner_directives"].append({
            "id": did,
            "content": content,
            "priority": priority,
            "active": True,
            "created": _now(),
        })
        self.save()
        return did

    # ── judgment packet compilation ──────────────────────────

    def compile_judgment_packet(
        self,
        task_tags: List[str],
        top_k: int = 15,
        include_warnings: bool = True,
        apply_decay: bool = True,
    ) -> Dict[str, Any]:
        """Compile a ranked set of scored entries relevant to the current task.

        This is the retrieval-to-action binding mechanism.  The strategist
        must cite, use, or explicitly dismiss each entry before planning.
        """
        now = _now()

        # Gather candidates
        candidates = []
        for entry in self.data["knowledge"]:
            tag_overlap = len(set(entry.get("tags", [])) & set(task_tags))
            if tag_overlap > 0 or not task_tags:
                if apply_decay:
                    bs = BetaScore.from_dict(entry["score"])
                    decay_confidence(bs, now=now)
                    entry["score"] = bs.to_dict()
                candidates.append(entry)

        ranked_knowledge = rank_entries(candidates, top_k=top_k)

        # Warnings always surface — they prevent repeated mistakes
        warnings = []
        if include_warnings:
            for w in self.data["warnings"]:
                tag_overlap = len(set(w.get("tags", [])) & set(task_tags))
                if tag_overlap > 0 or not task_tags:
                    warnings.append(w)

        # Active directives
        directives = [
            d for d in self.data["owner_directives"] if d.get("active", True)
        ]

        # Relevant entities
        entities = []
        for ent in self.data["entities"]:
            tag_overlap = len(set(ent.get("tags", [])) & set(task_tags))
            if tag_overlap > 0:
                entities.append(ent)

        # Relevant trajectories (ranked)
        traj_candidates = []
        for t in self.data["trajectories"]:
            tag_overlap = len(set(t.get("tags", [])) & set(task_tags))
            if tag_overlap > 0:
                traj_candidates.append(t)
        ranked_trajectories = rank_entries(traj_candidates, top_k=5)

        # Due pending outcomes
        pending_due = self.get_due_pending_outcomes()

        # Relevant recipes
        recipe = self.get_recipe(task_tags) if task_tags else None

        # Relationships for relevant entities
        relationships = []
        entity_ids = {e["id"] for e in entities}
        for rel in self.data.get("relationships", []):
            if rel["entity_a"] in entity_ids or rel["entity_b"] in entity_ids:
                relationships.append(rel)

        return {
            "task_tags": task_tags,
            "compiled_at": now,
            "cycle": self.data["cycle_count"],
            "directives": directives,
            "knowledge": ranked_knowledge,
            "warnings": warnings,
            "entities": entities,
            "relationships": relationships,
            "trajectories": ranked_trajectories,
            "pending_outcomes_due": pending_due,
            "recipe": recipe,
            "governance": self.data["governance"],
            "cost_compression": self.get_cost_compression_ratio(),
        }

    # ── cycle management ─────────────────────────────────────

    def begin_cycle(self) -> int:
        self.data["cycle_count"] += 1
        self.save()
        return self.data["cycle_count"]

    def journal_entry(self, cycle: int, event: str, details: Any = None) -> None:
        self.data["journal"].append({
            "cycle": cycle,
            "event": event,
            "details": details,
            "timestamp": _now(),
        })
        # Keep journal bounded
        if len(self.data["journal"]) > 500:
            self.data["journal"] = self.data["journal"][-500:]
        self.save()

    # ── stats ────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        pending = self.data.get("pending_outcomes", [])
        return {
            "cycles": self.data["cycle_count"],
            "knowledge_entries": len(self.data["knowledge"]),
            "warnings": len(self.data["warnings"]),
            "entities": len(self.data["entities"]),
            "trajectories": len(self.data["trajectories"]),
            "outcomes": len(self.data["outcomes"]),
            "proofs": len(self.data["proofs"]),
            "directives": len(self.data["owner_directives"]),
            "recipes": len(self.data.get("recipes", [])),
            "relationships": len(self.data.get("relationships", [])),
            "pending_outcomes": len([p for p in pending if not p.get("resolved")]),
            "cost_compression": self.get_cost_compression_ratio(),
            "journal_entries": len(self.data["journal"]),
        }

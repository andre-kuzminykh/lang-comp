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

        return {
            "task_tags": task_tags,
            "compiled_at": now,
            "cycle": self.data["cycle_count"],
            "directives": directives,
            "knowledge": ranked_knowledge,
            "warnings": warnings,
            "entities": entities,
            "trajectories": ranked_trajectories,
            "governance": self.data["governance"],
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
        return {
            "cycles": self.data["cycle_count"],
            "knowledge_entries": len(self.data["knowledge"]),
            "warnings": len(self.data["warnings"]),
            "entities": len(self.data["entities"]),
            "trajectories": len(self.data["trajectories"]),
            "outcomes": len(self.data["outcomes"]),
            "proofs": len(self.data["proofs"]),
            "directives": len(self.data["owner_directives"]),
            "journal_entries": len(self.data["journal"]),
        }

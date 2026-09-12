"""Orchestration Playbook (Layer 2): reusable, evolvable strategies.

`PlaybookMatcher.find_matching()` is consulted by the Planner *before* it
builds a plan from scratch: if a playbook's `conditions` are a subset of
the current task's context tags (built from intent categories, risk,
complexity, and detected project stack), and its active version's
confidence clears a threshold, the Planner adapts that strategy instead of
generating a new one. A weak or absent match falls through to the existing
rule-based/AI planning untouched -- "não seguir playbook cegamente".
"""

from __future__ import annotations

from dataclasses import dataclass

from core.database.repositories.playbooks_repo import (
    PlaybooksRepository,
    PlaybookVersionsRepository,
)

_MATCH_CONFIDENCE_THRESHOLD = 0.6

#: Seeded once at first run -- the two worked examples from the Stage 3
#: brief, translated into the (capability, step_type) strategy shape the
#: Planner already understands.
_SEED_PLAYBOOKS: tuple[dict, ...] = (
    {
        "task_type": "debugging",
        "name": "Debugging simples com contexto local suficiente",
        "conditions": ["risk:low"],
        "strategy": [
            {"capability": "debugging", "step_type": "implementation", "description": "Identificar e corrigir a causa do erro usando o contexto do projeto."},
            {"capability": "testing", "step_type": "verification", "description": "Executar testes para confirmar a correção."},
        ],
        "confidence": 0.6,
    },
    {
        "task_type": "architecture",
        "name": "Mudança de arquitetura com revisão independente",
        "conditions": [],
        "strategy": [
            {"capability": "architecture", "step_type": "planning", "description": "Propor a mudança de arquitetura."},
            {"capability": "coding", "step_type": "implementation", "description": "Implementar a mudança proposta."},
            {"capability": "analysis", "step_type": "review", "description": "Revisar a implementação de forma independente."},
        ],
        "confidence": 0.6,
    },
)


@dataclass(frozen=True)
class PlaybookMatch:
    playbook_id: str
    version_id: str
    name: str
    strategy: list[dict]
    confidence: float


class PlaybookMatcher:
    def __init__(self, playbooks_repo: PlaybooksRepository, versions_repo: PlaybookVersionsRepository) -> None:
        self._playbooks = playbooks_repo
        self._versions = versions_repo

    async def seed_defaults(self) -> None:
        existing = await self._playbooks.list_all()
        existing_names = {p["name"] for p in existing}
        for entry in _SEED_PLAYBOOKS:
            if entry["name"] in existing_names:
                continue
            playbook = await self._playbooks.create(
                task_type=entry["task_type"], name=entry["name"], conditions=entry["conditions"],
            )
            await self._versions.create_version(
                playbook["id"], strategy=entry["strategy"], confidence=entry["confidence"],
                reason="seed",
            )

    async def find_matching(self, *, task_type: str, context_tags: frozenset[str]) -> PlaybookMatch | None:
        candidates = await self._playbooks.list_active(task_type)
        best: PlaybookMatch | None = None
        best_specificity = -1
        for playbook in candidates:
            conditions = set(playbook["conditions"])
            if not conditions.issubset(context_tags):
                continue
            version = await self._versions.get_active(playbook["id"])
            if version is None or version["confidence"] < _MATCH_CONFIDENCE_THRESHOLD:
                continue
            # Prefer the most specific match (more conditions satisfied);
            # break ties by confidence.
            specificity = len(conditions)
            if best is None or specificity > best_specificity or (
                specificity == best_specificity and version["confidence"] > best.confidence
            ):
                best = PlaybookMatch(
                    playbook_id=playbook["id"], version_id=version["id"], name=playbook["name"],
                    strategy=version["strategy"], confidence=version["confidence"],
                )
                best_specificity = specificity
        return best

    async def record_outcome(self, version_id: str, *, success: bool) -> None:
        await self._versions.record_outcome(version_id, success=success)

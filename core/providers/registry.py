"""Model Registry: the single place model identifiers exist in this codebase.

No other module should ever hardcode a model id string. Instead:

    Provider -> ModelRegistry.models_for(provider) -> ModelInfo
                                                          |
                                                          v
                                                    capabilities, cost,
                                                    context window, priority

The Router picks a `ModelInfo` by capability/cost/priority (see
`core.orchestrator.router`); agents reference a *role* (`agent.model`, e.g.
"claude-architect-default") that resolves through this registry, not a raw
provider model string. Swapping which underlying model backs a role is a
registry edit (persisted in the `model_registry` table, seeded from
`DEFAULT_MODELS` below) -- never a code change.

Exact model id strings below are defaults and are expected to drift as
providers release new models; they are intentionally isolated to this one
list so updating them never touches routing, agent, or execution logic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    provider: str
    model_id: str
    display_name: str
    capabilities: tuple[str, ...] = ()
    context_window: int = 128_000
    supports_tools: bool = False
    supports_images: bool = False
    supports_files: bool = False
    supports_structured_output: bool = False
    input_cost_per_million_usd: float = 0.0
    output_cost_per_million_usd: float = 0.0
    priority: int = 0
    enabled: bool = True

    def estimate_cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens / 1_000_000 * self.input_cost_per_million_usd
            + output_tokens / 1_000_000 * self.output_cost_per_million_usd
        )


# Defaults seeded into the `model_registry` table on first startup (see
# core/database/repositories/model_registry_repo.py::seed_defaults). Editing
# these only changes what a *fresh* database starts with -- an existing
# database's rows (which the user may have edited) are never overwritten.
DEFAULT_MODELS: tuple[ModelInfo, ...] = (
    ModelInfo(
        provider="anthropic",
        model_id="claude-opus-5",
        display_name="Claude Opus 5",
        capabilities=("architecture", "security", "planning", "analysis", "coding"),
        context_window=200_000,
        supports_tools=True,
        supports_files=True,
        supports_structured_output=True,
        input_cost_per_million_usd=15.0,
        output_cost_per_million_usd=75.0,
        priority=10,
    ),
    ModelInfo(
        provider="anthropic",
        model_id="claude-sonnet-5",
        display_name="Claude Sonnet 5",
        capabilities=(
            "architecture", "coding", "debugging", "refactoring", "documentation",
            "security", "testing", "planning", "analysis",
        ),
        context_window=200_000,
        supports_tools=True,
        supports_files=True,
        supports_structured_output=True,
        input_cost_per_million_usd=3.0,
        output_cost_per_million_usd=15.0,
        priority=8,
    ),
    ModelInfo(
        provider="anthropic",
        model_id="claude-haiku-4-5",
        display_name="Claude Haiku 4.5",
        capabilities=("coding", "documentation", "general"),
        context_window=200_000,
        supports_tools=True,
        supports_files=True,
        supports_structured_output=True,
        input_cost_per_million_usd=0.8,
        output_cost_per_million_usd=4.0,
        priority=3,
    ),
    ModelInfo(
        provider="gemini",
        model_id="gemini-2.5-pro",
        display_name="Gemini 2.5 Pro",
        capabilities=("research", "analysis", "multimodal", "documentation", "planning"),
        context_window=1_000_000,
        supports_tools=True,
        supports_images=True,
        supports_files=True,
        supports_structured_output=True,
        input_cost_per_million_usd=1.25,
        output_cost_per_million_usd=5.0,
        priority=8,
    ),
    ModelInfo(
        provider="gemini",
        model_id="gemini-2.5-flash",
        display_name="Gemini 2.5 Flash",
        capabilities=("research", "analysis", "general", "multimodal"),
        context_window=1_000_000,
        supports_tools=True,
        supports_images=True,
        supports_structured_output=True,
        input_cost_per_million_usd=0.15,
        output_cost_per_million_usd=0.6,
        priority=5,
    ),
    ModelInfo(
        provider="openai",
        model_id="gpt-5.1",
        display_name="GPT-5.1",
        capabilities=("coding", "debugging", "testing", "refactoring", "general"),
        context_window=400_000,
        supports_tools=True,
        supports_files=True,
        supports_structured_output=True,
        input_cost_per_million_usd=2.5,
        output_cost_per_million_usd=10.0,
        priority=8,
    ),
    ModelInfo(
        provider="openai",
        model_id="gpt-5.1-codex",
        display_name="GPT-5.1 Codex",
        capabilities=("coding", "debugging", "testing", "refactoring"),
        context_window=400_000,
        supports_tools=True,
        supports_files=True,
        supports_structured_output=True,
        input_cost_per_million_usd=2.5,
        output_cost_per_million_usd=10.0,
        priority=9,
    ),
    ModelInfo(
        provider="mock",
        model_id="mock-general-1",
        display_name="Mock General",
        capabilities=(
            "coding", "debugging", "architecture", "research", "documentation",
            "security", "testing", "refactoring", "planning", "analysis",
            "multimodal", "general",
        ),
        context_window=32_000,
        supports_tools=True,
        supports_structured_output=True,
        priority=1,
    ),
)


class ModelRegistry:
    """In-memory view over the model catalog.

    Backed by the `model_registry` table (via
    `core.database.repositories.model_registry_repo.ModelRegistryRepository`)
    for persistence and user edits; this class holds the working set the
    Router actually queries against during an execution, refreshed from the
    database at startup (see `core.bridge.context.build_context`).
    """

    def __init__(self, models: list[ModelInfo] | None = None) -> None:
        self._models: dict[tuple[str, str], ModelInfo] = {
            (m.provider, m.model_id): m for m in (models if models is not None else DEFAULT_MODELS)
        }

    def all(self, *, only_enabled: bool = True) -> list[ModelInfo]:
        models = list(self._models.values())
        if only_enabled:
            models = [m for m in models if m.enabled]
        return models

    def for_provider(self, provider: str, *, only_enabled: bool = True) -> list[ModelInfo]:
        return [m for m in self.all(only_enabled=only_enabled) if m.provider == provider]

    def get(self, provider: str, model_id: str) -> ModelInfo | None:
        return self._models.get((provider, model_id))

    def by_capability(self, capability: str, *, only_enabled: bool = True) -> list[ModelInfo]:
        matches = [m for m in self.all(only_enabled=only_enabled) if capability in m.capabilities]
        return sorted(matches, key=lambda m: m.priority, reverse=True)

    def upsert(self, model: ModelInfo) -> None:
        self._models[(model.provider, model.model_id)] = model

    def set_enabled(self, provider: str, model_id: str, enabled: bool) -> None:
        existing = self._models.get((provider, model_id))
        if existing is not None:
            self._models[(provider, model_id)] = _replace_enabled(existing, enabled)


def _replace_enabled(model: ModelInfo, enabled: bool) -> ModelInfo:
    return ModelInfo(
        provider=model.provider,
        model_id=model.model_id,
        display_name=model.display_name,
        capabilities=model.capabilities,
        context_window=model.context_window,
        supports_tools=model.supports_tools,
        supports_images=model.supports_images,
        supports_files=model.supports_files,
        supports_structured_output=model.supports_structured_output,
        input_cost_per_million_usd=model.input_cost_per_million_usd,
        output_cost_per_million_usd=model.output_cost_per_million_usd,
        priority=model.priority,
        enabled=enabled,
    )

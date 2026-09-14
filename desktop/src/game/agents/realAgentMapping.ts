/**
 * Stage 3: the office has exactly 4 named, visual roles (Gemini CEO,
 * Gemini Designer, Codex, Claude Code), but `core/agents/registry.py`
 * has 11 real logical agents (mock ones for offline/tests, HTTP-API
 * ones, and the two real, authenticated CLI ones). This is the one
 * place that decides which real agent_id's activity is represented by
 * which visual character -- a deterministic table, not inferred per
 * event, so the mapping is stable and auditable.
 *
 * The two CLI-backed agents (`agent_codex_cli_developer`,
 * `agent_claude_code_architect`) map to the roles their names have
 * consistently meant throughout this project (Codex = Frontend
 * Developer, Claude Code = Backend Developer) even though
 * `agent_claude_code_architect`'s own capabilities also include
 * architecture/planning -- a deliberate, documented simplification
 * (see GAME_ENGINE.md) rather than a second axis of ambiguity.
 */
export const REAL_AGENT_TO_VISUAL: Record<string, string> = {
  agent_generalist: "agent_gemini_ceo",
  agent_reviewer: "agent_claude_code",
  agent_coder: "agent_codex",
  agent_claude_architect: "agent_gemini_ceo",
  agent_claude_reviewer: "agent_claude_code",
  agent_gemini_researcher: "agent_gemini_designer",
  agent_gemini_analyst: "agent_gemini_designer",
  agent_codex_developer: "agent_codex",
  agent_codex_tester: "agent_codex",
  agent_codex_cli_developer: "agent_codex",
  agent_claude_code_architect: "agent_claude_code",
};

export function visualAgentFor(realAgentId: string): string | null {
  return REAL_AGENT_TO_VISUAL[realAgentId] ?? null;
}

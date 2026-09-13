import type { Agent } from "@/types";
import type { RoomId } from "@/office/types";

/**
 * Maps a real backend capability category (see
 * `core/orchestrator/planner.py`'s fixed category list) to the room where
 * work of that kind happens. This is a seating/labeling convention, not
 * fabricated activity -- an agent only ever appears in a room because a
 * *real* step with that `required_capability` is actually assigned to it.
 *
 * Honest limitation, not hidden: the backend has no first-class "design"
 * capability yet, so `design_desk` is populated from the closest real
 * categories (research/documentation/multimodal) rather than a true UI/UX
 * signal. See VIRTUAL_OFFICE.md.
 */
const CAPABILITY_TO_ROOM: Record<string, RoomId> = {
  architecture: "ceo_office",
  planning: "ceo_office",
  coding: "backend_desk",
  debugging: "backend_desk",
  refactoring: "backend_desk",
  research: "design_desk",
  documentation: "design_desk",
  multimodal: "design_desk",
  analysis: "design_desk",
  testing: "testing_lab",
  security: "testing_lab",
  general: "lounge",
};

/** Codex-family agents (CLI or API) sit at the Frontend Desk instead of
 * the Backend Desk for the same "coding" capability -- purely a seating
 * convention for visual variety when multiple coding agents work in
 * parallel (the DAG genuinely does run steps concurrently); it does not
 * change what work is actually assigned to whom. */
const FRONTEND_DESK_AGENT_IDS = new Set([
  "agent_codex_developer",
  "agent_codex_tester",
  "agent_codex_cli_developer",
  "agent_coder",
]);

export function roomForCapability(capability: string, agentId: string): RoomId {
  if ((capability === "coding" || capability === "debugging" || capability === "refactoring") &&
    FRONTEND_DESK_AGENT_IDS.has(agentId)) {
    return "frontend_desk";
  }
  return CAPABILITY_TO_ROOM[capability] ?? "lounge";
}

export function homeRoomForAgent(agent: Agent): RoomId {
  const primaryCapability = agent.capabilities[0]?.name ?? "general";
  return roomForCapability(primaryCapability, agent.id);
}

/** Short, human role label shown in tooltips/panels -- derived from the
 * agent's own registered capabilities, never invented. */
export function roleLabelForAgent(agent: Agent): string {
  const names = agent.capabilities.map((c) => c.name);
  if (names.includes("architecture") || names.includes("planning")) return "Architect / Orchestrator";
  if (names.includes("coding") || names.includes("debugging") || names.includes("refactoring")) {
    return FRONTEND_DESK_AGENT_IDS.has(agent.id) ? "Frontend Developer" : "Backend Developer";
  }
  if (names.includes("testing") || names.includes("security")) return "QA / Security";
  if (names.includes("research") || names.includes("documentation") || names.includes("multimodal")) {
    return "Research & Design";
  }
  return "Generalist";
}

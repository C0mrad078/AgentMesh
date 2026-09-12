import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", () => ({
  learningApi: {
    policy: vi.fn(),
    setPolicy: vi.fn(),
    rules: vi.fn(),
    candidates: vi.fn(),
    approveCandidate: vi.fn(),
    rejectCandidate: vi.fn(),
    pinRule: vi.fn(),
    unpinRule: vi.fn(),
    rollbackRule: vi.fn(),
    createRule: vi.fn(),
  },
  playbooksApi: {
    list: vi.fn(),
    versions: vi.fn(),
  },
  modelPerformanceApi: {
    list: vi.fn(),
  },
  contextOptimizerApi: {
    suggestions: vi.fn(),
  },
  promptsApi: {
    versions: vi.fn(),
    rollback: vi.fn(),
    proposals: vi.fn(),
    applyProposal: vi.fn(),
  },
  agentsApi: {
    list: vi.fn(),
  },
}));

import {
  agentsApi,
  contextOptimizerApi,
  learningApi,
  modelPerformanceApi,
  playbooksApi,
  promptsApi,
} from "@/services/api";
import { LearningPage } from "@/pages/LearningPage";
import type { LearnedRule, LearningCandidate, LearningPolicy, Playbook } from "@/types";

const POLICY: LearningPolicy = {
  id: "global",
  mode: "assisted",
  minimum_observations_for_activation: 5,
  minimum_confidence: 0.75,
  auto_apply_categories: ["playbook"],
  requires_approval_categories: ["prompt", "routing", "verification"],
  max_changes_per_day: 5,
  rollback_threshold: 0.2,
  updated_at: "now",
};

const RULE: LearnedRule = {
  id: "rule_1",
  project_id: null,
  title: "Evitar Gemini em debugging local",
  category: "agent_selection",
  action: { effect: "avoid_agent", agent_id: "agent_gemini_researcher" },
  scope_type: "agent",
  scope_value: "agent_gemini_researcher",
  priority: "normal",
  status: "active",
  confidence: 0.87,
  observations: 12,
  successes: 11,
  failures: 1,
  distinct_projects: ["p1", "p2"],
  pinned: false,
  source: "learning_engine",
  last_observed_at: "now",
  created_at: "now",
  updated_at: "now",
};

const CANDIDATE: LearningCandidate = {
  id: "candidate_1",
  category: "planning",
  title: "Paralelizar categorias independentes",
  rule_text: "Avaliar se etapas independentes podem rodar em paralelo.",
  scope_type: "task_type",
  scope_value: "debugging",
  normalized_key: "k",
  observations: 2,
  successes: 2,
  failures: 0,
  distinct_projects: ["p1"],
  confidence: 0.3,
  status: "observing",
  promoted_rule_id: null,
  rejection_reason: null,
  created_at: "now",
  updated_at: "now",
};

const PLAYBOOK: Playbook = {
  id: "playbook_1",
  task_type: "debugging",
  name: "Debugging simples",
  conditions: ["risk:low"],
  status: "active",
  origin: "seed",
  created_at: "now",
  updated_at: "now",
};

describe("LearningPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(learningApi.policy).mockResolvedValue(POLICY);
    vi.mocked(learningApi.rules).mockResolvedValue([RULE]);
    vi.mocked(learningApi.candidates).mockResolvedValue([CANDIDATE]);
    vi.mocked(playbooksApi.list).mockResolvedValue([PLAYBOOK]);
    vi.mocked(playbooksApi.versions).mockResolvedValue([]);
    vi.mocked(modelPerformanceApi.list).mockResolvedValue([]);
    vi.mocked(contextOptimizerApi.suggestions).mockResolvedValue([]);
    vi.mocked(promptsApi.versions).mockResolvedValue([]);
    vi.mocked(promptsApi.proposals).mockResolvedValue([]);
    vi.mocked(agentsApi.list).mockResolvedValue([]);
  });

  it("shows overview stats from policy, rules, and candidates", async () => {
    render(<LearningPage />);
    expect(await screen.findByText("Regras ativas")).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText("1")).toHaveLength(3));
    expect(screen.getByText("assisted")).toBeInTheDocument();
  });

  it("changes the learning mode", async () => {
    vi.mocked(learningApi.setPolicy).mockResolvedValue({ ...POLICY, mode: "manual" });
    render(<LearningPage />);
    await screen.findByRole("button", { name: "Manual" });

    await userEvent.click(screen.getByRole("button", { name: "Manual" }));
    await waitFor(() => expect(learningApi.setPolicy).toHaveBeenCalledWith({ mode: "manual" }));
  });

  it("lists rules and toggles pin", async () => {
    render(<LearningPage />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Regras" }));

    expect(await screen.findByText("Evitar Gemini em debugging local")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Fixar" }));
    await waitFor(() => expect(learningApi.pinRule).toHaveBeenCalledWith("rule_1"));
  });

  it("approves a candidate", async () => {
    render(<LearningPage />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Candidatos" }));

    expect(await screen.findByText("Paralelizar categorias independentes")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Aprovar" }));
    await waitFor(() => expect(learningApi.approveCandidate).toHaveBeenCalledWith("candidate_1"));
  });

  it("lists playbooks", async () => {
    render(<LearningPage />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Playbooks" }));

    expect(await screen.findByText("Debugging simples")).toBeInTheDocument();
  });

  it("shows context optimizer suggestions in the performance tab", async () => {
    vi.mocked(contextOptimizerApi.suggestions).mockResolvedValue([
      {
        task_category: "debugging", samples: 6, avg_files_included: 4, avg_files_used: 1,
        usage_ratio: 0.25, suggestion: "reduce", detail: "Apenas 25% dos arquivos são usados.",
        rarely_used_extensions: [".md"],
      },
    ]);
    render(<LearningPage />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Desempenho" }));

    expect(await screen.findByText("Apenas 25% dos arquivos são usados.")).toBeInTheDocument();
  });

  it("shows a pending prompt proposal and applies it", async () => {
    vi.mocked(promptsApi.proposals).mockResolvedValue([
      {
        id: "evt_1", event_type: "prompt_proposal_generated", target_type: "prompt",
        target_id: "agent_claude_reviewer", actor: "learning_engine",
        evidence: {
          owner_key: "agent_claude_reviewer", prompt_type: "agent", agent_id: "agent_claude_reviewer",
          current_version_id: "prompt_1", proposed_content: "Revise o código verificando concorrência.",
          reason: "Reflexão identificou pontos a revisar.", evidence_summary: "verificar concorrência",
        },
        created_at: "now",
      },
    ]);
    render(<LearningPage />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Prompts" }));

    expect(await screen.findByText("agent_claude_reviewer")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Aplicar" }));
    await waitFor(() => expect(promptsApi.applyProposal).toHaveBeenCalledWith("evt_1"));
  });
});

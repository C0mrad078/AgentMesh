import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { OnboardingPage } from '@/pages/OnboardingPage';
import type { Project } from '@/types';

const mocks = vi.hoisted(() => {
  const project: Project = { id: 'p1', name: 'Projeto demo', description: '', workspace_path: '/workspace', status: 'active', config: {}, created_at: 'now', updated_at: 'now' };
  const projectsState = { projects: [project] as Project[], selectedProjectId: 'p1' as string | null, loading: false, loaded: true, error: null as string | null, loadProjects: vi.fn(), createProject: vi.fn(), selectProject: vi.fn() };
  const agentsState = { agents: [] as Array<{ id: string; name: string; role: string; provider: string; project_id: string | null; runtime_binding_id?: string | null }>, loaded: true, error: null as string | null, loadAgents: vi.fn(), createAgent: vi.fn(), updateAgent: vi.fn() };
  const reliabilityState = { diagnostics: { providers: [{ name: 'git', available: true, version: '2.4' }, { name: 'gh', available: false }] }, errors: {} as Record<string, string | undefined>, refresh: vi.fn() };
  return { project, projectsState, agentsState, reliabilityState, setActivePage: vi.fn(), providerList: vi.fn(), cliList: vi.fn(), bindingList: vi.fn(), modelList: vi.fn(), bindingCreate: vi.fn(), missionCreate: vi.fn(), missionCommand: vi.fn() };
});

vi.mock('@/stores/projectsStore', () => ({ useProjectsStore: (selector?: (state: typeof mocks.projectsState) => unknown) => selector ? selector(mocks.projectsState) : mocks.projectsState }));
vi.mock('@/stores/agentsStore', () => ({ useAgentsStore: (selector?: (state: typeof mocks.agentsState) => unknown) => selector ? selector(mocks.agentsState) : mocks.agentsState }));
vi.mock('@/stores/reliabilityStore', () => ({ useReliabilityStore: (selector?: (state: typeof mocks.reliabilityState) => unknown) => selector ? selector(mocks.reliabilityState) : mocks.reliabilityState }));
vi.mock('@/stores/uiStore', () => ({ useUiStore: (selector: (state: { setActivePage: typeof mocks.setActivePage }) => unknown) => selector({ setActivePage: mocks.setActivePage }) }));
vi.mock('@/services/api', () => ({
  providersApi: { list: mocks.providerList }, providerCliApi: { listStatuses: mocks.cliList }, modelsApi: { list: mocks.modelList },
  runtimeBindingsApi: { list: mocks.bindingList, create: mocks.bindingCreate },
  agentsApi: { create: vi.fn(), update: vi.fn() },
}));
vi.mock('@/missions/api', () => ({ missionsApi: { create: mocks.missionCreate, command: mocks.missionCommand } }));

const binding = { id: 'b1', provider_id: 'codex_cli', account_id: null, label: 'Codex', configured_capacity: 2, observed_capacity: 2, reserved_slots: 0, health: 'healthy', enabled: true, backoff_until: null };
const mission = { schema_version: 1, id: 'm1', project_id: 'p1', request: 'Build feature', status: 'analyzing', reason: '', current_plan_id: null, result: '', created_at: 'now', updated_at: 'now' } as const;

beforeEach(() => {
  vi.clearAllMocks();
  Object.assign(mocks.projectsState, { projects: [mocks.project], selectedProjectId: 'p1', loading: false, loaded: true, error: null });
  Object.assign(mocks.agentsState, { agents: [], loaded: true, error: null });
  Object.assign(mocks.reliabilityState, { diagnostics: { providers: [{ name: 'git', available: true, version: '2.4' }, { name: 'gh', available: false }] }, errors: {} });
  mocks.projectsState.loadProjects.mockResolvedValue(undefined); mocks.agentsState.loadAgents.mockResolvedValue(undefined); mocks.reliabilityState.refresh.mockResolvedValue(undefined);
  mocks.providerList.mockResolvedValue([{ provider: 'openai', display_name: 'OpenAI', enabled: true, connected: true, health: 'online' }]);
  mocks.cliList.mockResolvedValue({ codex_cli: { access_method: 'cli', state: 'connected', version: '1.0', auth_method: 'subscription', model: 'x', detail: null }, claude_code_cli: { access_method: 'cli', state: 'not_installed', version: null, auth_method: null, model: null, detail: null }, gemini_cli: { access_method: 'cli', state: 'disconnected', version: null, auth_method: null, model: null, detail: null } });
  mocks.bindingList.mockResolvedValue([binding]); mocks.modelList.mockResolvedValue([]);
  mocks.bindingCreate.mockResolvedValue({ ...binding, id: 'b2', label: 'Novo' });
  mocks.missionCreate.mockResolvedValue(mission); mocks.missionCommand.mockResolvedValue(mission);
  mocks.agentsState.createAgent.mockResolvedValue({ id: 'a1', name: 'Agente novo', role: 'worker', provider: 'openai', project_id: 'p1' });
  mocks.agentsState.updateAgent.mockResolvedValue({});
});
afterEach(cleanup);

describe('OnboardingPage', () => {
  it('shows detected CLI/authentication, real capacity and ready checklist', async () => {
    mocks.agentsState.agents = [{ id: 'a1', name: 'Agente', role: 'worker', provider: 'openai', project_id: 'p1' }];
    render(<OnboardingPage />);
    expect(await screen.findByText('GitHub CLI (gh)')).toBeInTheDocument();
    expect(screen.getByText('autenticado (subscription)')).toBeInTheDocument();
    expect(screen.getByText(/2\/2 · slots reservados: 0/)).toBeInTheDocument();
    expect(await screen.findByText('Capacidade mínima observada; onboarding pode ser concluído.')).toBeInTheDocument();
    expect(screen.getByText('Primeiro uso', { selector: 'p' })).toBeInTheDocument();
  });

  it('creates a project through the existing project API', async () => {
    mocks.projectsState.createProject.mockResolvedValue(mocks.project);
    render(<OnboardingPage />);
    await userEvent.type(screen.getAllByRole('textbox')[0], 'Novo workspace');
    await userEvent.click(screen.getByRole('button', { name: 'Criar e selecionar projeto' }));
    await waitFor(() => expect(mocks.projectsState.createProject).toHaveBeenCalledWith({ name: 'Novo workspace', description: '', }));
  });

  it('starts the first mission only after create and analyze receive backend responses', async () => {
    render(<OnboardingPage />);
    const textbox = screen.getByLabelText('O que você quer realizar?');
    await userEvent.type(textbox, 'Build feature');
    await userEvent.click(screen.getByRole('button', { name: 'Criar e iniciar missão' }));
    await waitFor(() => expect(mocks.missionCreate).toHaveBeenCalledWith('p1', 'Build feature', expect.any(String)));
    expect(mocks.missionCommand).toHaveBeenCalledWith('m1', { action: 'analyze' }, expect.any(String));
    expect(await screen.findByText('Primeira missão enviada para análise pelo backend.')).toBeInTheDocument();
  });

  it('reports mission-created but not-started when analysis fails, without optimistic success', async () => {
    mocks.missionCommand.mockRejectedValueOnce(new Error('provider rate limited'));
    render(<OnboardingPage />);
    await userEvent.type(screen.getByLabelText('O que você quer realizar?'), 'Build feature');
    await userEvent.click(screen.getByRole('button', { name: 'Criar e iniciar missão' }));
    expect(await screen.findByText('Missão criada, início/análise não confirmado.')).toBeInTheDocument();
    expect(screen.queryByText('Primeira missão enviada para análise pelo backend.')).not.toBeInTheDocument();
    expect(screen.getAllByRole('alert').some(element => element.textContent?.includes('provider rate limited'))).toBe(true);
  });

  it('gracefully handles first use with no projects, no provider, or CLI statuses', async () => {
    mocks.projectsState.projects = []; mocks.projectsState.selectedProjectId = null;
    mocks.providerList.mockResolvedValue([]); mocks.cliList.mockResolvedValue({ codex_cli: { access_method: 'cli', state: 'not_installed', version: null, auth_method: null, model: null, detail: null } });
    render(<OnboardingPage />);
    expect(await screen.findByText('Primeiro uso: nenhum projeto cadastrado.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Criar e iniciar missão' })).toBeDisabled();
    expect(screen.getByText('não reportado')).toBeInTheDocument();
  });
});

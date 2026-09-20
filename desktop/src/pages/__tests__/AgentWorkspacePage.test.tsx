import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AgentWorkspacePage } from '../AgentWorkspacePage';
import { useMissionStore } from '@/missions/store';
import { useProjectsStore } from '@/stores/projectsStore';
import { useUiStore } from '@/stores/uiStore';
import { BottomNav } from '@/layouts/BottomNav';
import { agent, snapshot } from '@/missions/__tests__/fixtures';
import { missionsApi } from '@/missions/api';
import type { WorkspaceNode } from '@/missions/projection';
vi.mock('@xyflow/react', () => ({
  ReactFlow: ({ nodes, onNodeClick }: { nodes: WorkspaceNode[]; onNodeClick: (e: unknown, node: WorkspaceNode) => void }) => <div>{nodes.map(n => <button key={n.id} onClick={() => onNodeClick(null, n)}>{n.data.label}</button>)}</div>,
  Background: () => null, Controls: () => null, MiniMap: () => null,
}));
vi.mock('@/services/bridge', () => ({ onBridgeEvent: vi.fn().mockResolvedValue(() => undefined) }));
vi.mock('@/missions/api', () => ({ missionsApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), command: vi.fn() } }));
vi.mock('@/services/api', () => ({
  agentsApi: { list: vi.fn(async () => [agent]) }, providerCliApi: { listStatuses: vi.fn(async () => ({ codex_cli: { state: 'connected' } })) },
  settingsApi: { get: vi.fn(async () => ({ value: '' })), update: vi.fn(async () => ({})) },
}));
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(missionsApi.list).mockResolvedValue([snapshot.mission]);
  vi.mocked(missionsApi.get).mockResolvedValue(snapshot);
  vi.mocked(missionsApi.create).mockResolvedValue(snapshot.mission);
  vi.mocked(missionsApi.command).mockResolvedValue(snapshot.mission);
  useProjectsStore.setState({ projects: [{ id: 'project-1', name: 'Example', description: '', workspace_path: '/project', status: 'active', config: {}, created_at: '', updated_at: '' }], selectedProjectId: 'project-1', loadProjects: vi.fn().mockResolvedValue(undefined) });
  useMissionStore.setState({ selectedId: null, snapshot: null, missions: [], projectId: null, error: null, sending: false });
});
describe('Agent Workspace', () => {
  it('shows plan, real provider state and persistent conversation', async () => {
    render(<AgentWorkspacePage />);
    expect(await screen.findByText('Please cover empty inputs')).toBeInTheDocument();
    expect(screen.getByText('connected')).toBeInTheDocument();
    expect(screen.getByText('Fix and review')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Iniciar missão' })).toBeEnabled();
  });
  it('submits a natural request then asks the backend to analyze', async () => {
    render(<AgentWorkspacePage />);
    await screen.findByText('Fix and review');
    await userEvent.type(screen.getByLabelText('Pedido ou instrução'), 'Fix a bug');
    await userEvent.click(screen.getByRole('button', { name: 'Enviar pedido' }));
    await waitFor(() => expect(missionsApi.create).toHaveBeenCalledWith('project-1', 'Fix a bug', expect.any(String)));
    expect(missionsApi.command).toHaveBeenCalledWith('mission-1', { action: 'analyze' }, expect.any(String));
  });
  it('filters messages and keeps Pixel Office navigation in both directions', async () => {
    render(<><AgentWorkspacePage /><BottomNav /></>);
    await screen.findByText('Please cover empty inputs');
    await userEvent.type(screen.getByLabelText('Filtrar conversa'), 'missing');
    expect(screen.queryByText('Please cover empty inputs')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Pixel Office' }));
    expect(useUiStore.getState().activePage).toBe('office');
    await userEvent.click(screen.getByTestId('nav-collaboration'));
    expect(useUiStore.getState().activePage).toBe('collaboration');
  });
  it('opens session logs and sends session pause to backend', async () => {
    render(<AgentWorkspacePage />);
    await userEvent.click(await screen.findByRole('button', { name: /Sessão/ }));
    expect(screen.getByText('Terminal / logs da sessão')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Pausar sessão' }));
    expect(missionsApi.command).toHaveBeenCalledWith('mission-1', { action: 'pause', session_id: 'session-1' }, expect.any(String));
  });
});

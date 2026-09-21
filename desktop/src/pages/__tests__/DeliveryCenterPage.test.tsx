import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DeliveryCenterPage } from '../DeliveryCenterPage';
import { deliveryApi } from '@/services/deliveryApi';
import { useDeliveryStore } from '@/stores/deliveryStore';
import { useUiStore } from '@/stores/uiStore';
import { detail, summary } from '@/components/delivery/__tests__/fixtures';
import type { DeliveryCandidateDetail, DeliveryStatus } from '@/types/delivery';
vi.mock('@/services/bridge', () => ({ onBridgeEvent: vi.fn().mockResolvedValue(() => undefined) }));
vi.mock('@/services/deliveryApi', () => ({ deliveryApi: Object.fromEntries(['get', 'list', 'create', 'preflight', 'binding', 'saveBinding', 'approve', 'push', 'createPr', 'updatePr', 'ci', 'assignFix', 'merge', 'proposeRollback', 'rollback', 'telemetry'].map(k => [k, vi.fn()])) }));
let data: DeliveryCandidateDetail;
beforeEach(() => {
  vi.clearAllMocks(); data = detail();
  useDeliveryStore.setState({ candidates: [], detail: null, selectedId: null, loading: false, busy: false, error: null, progress: null });
  useUiStore.setState({ activePage: 'delivery', deliveryCandidateId: 'candidate-1' });
  vi.mocked(deliveryApi.get).mockImplementation(async () => data);
  vi.mocked(deliveryApi.list).mockImplementation(async () => [summary(data)]);
});
afterEach(cleanup);
async function ready() { render(<DeliveryCenterPage />); await screen.findByRole('region', { name: 'Candidate e evidências congeladas' }); }
describe('Delivery Center', () => {
  it('renders loading then frozen snapshot, files and all operational panels', async () => {
    let resolve!: (d: DeliveryCandidateDetail) => void;
    vi.mocked(deliveryApi.get).mockReturnValue(new Promise(r => { resolve = r; }));
    render(<DeliveryCenterPage />);
    expect(screen.getByText('Carregando delivery…')).toBeInTheDocument();
    await act(async () => resolve(data));
    expect(screen.getByText('src/delivery.ts · added · +2 / −1')).toBeInTheDocument();
    for (const name of ['Preflight e segurança', 'Remote e target branch', 'CI e status checks', 'Falhas de CI e correções', 'Aprovações humanas', 'Pós-merge e rollback por revert', 'Telemetria por fase']) expect(screen.getByRole('region', { name })).toBeInTheDocument();
    expect(screen.getByText('integration-sha')).toBeInTheDocument();
  });
  it('shows empty list and creates a candidate using explicit project and mission', async () => {
    useUiStore.setState({ deliveryCandidateId: null }); vi.mocked(deliveryApi.list).mockResolvedValue([]); vi.mocked(deliveryApi.create).mockResolvedValue(data);
    render(<DeliveryCenterPage />); expect(await screen.findByText('Nenhum candidate criado.')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Project ID'), 'project-1'); await userEvent.type(screen.getByLabelText('Mission ID'), 'mission-1');
    await userEvent.click(screen.getByRole('button', { name: 'Congelar candidate' }));
    await waitFor(() => expect(deliveryApi.create).toHaveBeenCalledWith('mission-1', 'project-1'));
  });
  it('recovers from load failure without inventing success', async () => {
    vi.mocked(deliveryApi.get).mockRejectedValueOnce(new Error('Bridge offline'));
    render(<DeliveryCenterPage />); expect(await screen.findByRole('alert')).toHaveTextContent('Bridge offline');
    await userEvent.click(screen.getByRole('button', { name: 'Tentar novamente' }));
    await screen.findByRole('region', { name: 'Candidate e evidências congeladas' });
  });
  it.each<DeliveryStatus>(['preflight_failed', 'pr_open', 'ci_running', 'awaiting_merge_approval', 'merged', 'rollback_proposed', 'rolled_back', 'blocked', 'cancelled', 'rejected'])('renders persisted %s state', async status => {
    data.candidate.status = status; await ready(); expect(screen.getByText(new RegExp(`· ${status}$`))).toBeInTheDocument();
  });
  it('renders backend recovery reason and refreshes persisted state', async () => {
    data.recovery = { is_blocked: true, recovery_reason: 'human_input_required', suggested_action: 'human_intervention' }; await ready();
    expect(screen.getByRole('alert')).toHaveTextContent('human_input_required');
    await userEvent.click(screen.getByRole('button', { name: 'Recuperar estado persistido' }));
    expect(deliveryApi.get).toHaveBeenCalledTimes(2);
  });
  it.each(['push', 'pr_create', 'pr_update', 'merge', 'rollback'] as const)('requires human identity for %s approval and never executes implicitly', async action => {
    data.pending_approvals = [action]; await ready();
    await userEvent.click(screen.getByRole('button', { name: /Revisar:/ }));
    const modal = screen.getByRole('dialog'); expect(within(modal).getByRole('button', { name: 'Registrar aprovação' })).toBeDisabled();
    await userEvent.type(within(modal).getByLabelText('Identificação do aprovador'), 'human');
    await userEvent.click(within(modal).getByRole('button', { name: 'Registrar aprovação' }));
    await waitFor(() => expect(deliveryApi.approve).toHaveBeenCalledWith('candidate-1', action, 'approved', 'human', ''));
    expect(deliveryApi.push).not.toHaveBeenCalled(); expect(deliveryApi.merge).not.toHaveBeenCalled(); expect(deliveryApi.rollback).not.toHaveBeenCalled();
  });
  it('sends rejection with reason', async () => {
    data.pending_approvals = ['merge']; await ready(); await userEvent.click(screen.getByRole('button', { name: 'Revisar: Merge' }));
    await userEvent.type(screen.getByLabelText('Identificação do aprovador'), 'reviewer'); await userEvent.type(screen.getByLabelText('Motivo da decisão'), 'Needs review');
    await userEvent.click(screen.getByRole('button', { name: 'Rejeitar' }));
    expect(deliveryApi.approve).toHaveBeenCalledWith('candidate-1', 'merge', 'rejected', 'reviewer', 'Needs review');
  });
  it('preserves idempotency key on retry and reports denied remote action', async () => {
    vi.mocked(deliveryApi.push).mockRejectedValue(new Error('Approval required')); await ready();
    await userEvent.click(screen.getByRole('button', { name: 'Push da branch' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Approval required');
    await userEvent.click(screen.getByRole('button', { name: 'Push da branch' }));
    expect(vi.mocked(deliveryApi.push).mock.calls[0]).toEqual(vi.mocked(deliveryApi.push).mock.calls[1]);
  });
  it('copies a sanitized report without secret samples or metadata credentials', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    data.preflight = { id: 'pf', candidate_id: 'candidate-1', version: 1, status: 'failed', remote_reachable: true, base_up_to_date: true, clean_integration_tree: true, quality_gate_passed: true, secret_scan_passed: false, secret_findings: [{ file_path: 'env', rule_id: 'secret', masked_sample: 'sample-must-not-leak', line_number: 1 }], large_binary_findings: [], migration_lockfile_check: { status: 'passed', details: '' }, risk_level: 'high', blocking_reasons: [], executed_at: 'now' };
    data.internal_steps = [{ id: 'step', candidate_id: 'candidate-1', name: 'push', status: 'failed', metadata: { password: 'metadata-must-not-leak' }, created_at: 'now', updated_at: 'now' }];
    await ready(); await userEvent.click(screen.getByRole('button', { name: 'Copiar relatório sanitizado' }));
    const copied = writeText.mock.calls[0][0] as string;
    expect(copied).not.toContain('sample-must-not-leak'); expect(copied).not.toContain('metadata-must-not-leak'); expect(copied).toContain('[mascarado]');
  });
  it('reports clipboard failure without claiming success', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn().mockRejectedValue(new Error('Denied')) }, configurable: true });
    await ready(); await userEvent.click(screen.getByRole('button', { name: 'Copiar relatório sanitizado' }));
    expect(await screen.findByText('Não foi possível copiar o relatório.')).toBeInTheDocument();
  });
  it('assigns a CI correction and proposes revert via the bridge', async () => {
    data.ci_findings = [{ id: 'finding', candidate_id: 'candidate-1', check_id: 'check', classification: 'test_failure', assigned_task_id: null, assigned_agent_id: null, worktree_path: null, iteration: 1, status: 'analyzing' }]; await ready();
    await userEvent.type(screen.getByLabelText('Agent ID para finding'), 'agent-2'); await userEvent.click(screen.getByRole('button', { name: 'Atribuir correção' }));
    expect(deliveryApi.assignFix).toHaveBeenCalledWith('candidate-1', 'finding', 'agent-2');
    await userEvent.type(screen.getByLabelText('Motivo do rollback'), 'Regression'); await userEvent.click(screen.getByRole('button', { name: 'Propor rollback por revert' }));
    expect(deliveryApi.proposeRollback).toHaveBeenCalledWith('candidate-1', 'Regression');
  });
});

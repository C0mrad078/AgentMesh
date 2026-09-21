import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PreflightCard } from '../PreflightCard';
import { TelemetryCard } from '../TelemetryCard';
import { CiStatusCard } from '../CiStatusCard';
import { RemoteBindingCard } from '../RemoteBindingCard';
import { RollbackCard } from '../RollbackCard';
import { ExternalLink } from '../Panel';
import { safeText } from '../presentation';
import type { PhaseTelemetry, PreflightReport } from '@/types/delivery';
const report: PreflightReport = { id: 'p1', candidate_id: 'c1', version: 1, status: 'failed', remote_reachable: true, base_up_to_date: false, clean_integration_tree: true, quality_gate_passed: false, secret_scan_passed: false, secret_findings: [{ file_path: 'config.env', rule_id: 'credential', masked_sample: 'must-never-render', line_number: 3 }], large_binary_findings: [{ file_path: 'large.bin', size_bytes: 5000000 }], migration_lockfile_check: { status: 'passed', details: 'Checked' }, risk_level: 'critical', blocking_reasons: ['Base behind target'], executed_at: '2026-09-21' };
afterEach(cleanup);
describe('Delivery cards', () => {
  it('masks secret samples regardless of backend content and exposes blockers', async () => {
    const run = vi.fn(); render(<PreflightCard report={report} busy={false} onRun={run} />);
    expect(screen.queryByText('must-never-render')).not.toBeInTheDocument(); expect(screen.getByText(/conteúdo mascarado/)).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Base behind target'); await userEvent.click(screen.getByRole('button', { name: 'Repetir preflight' })); expect(run).toHaveBeenCalledOnce();
  });
  it('keeps unknown telemetry distinct from measured zero', () => {
    const p: PhaseTelemetry = { id: 'phase', mission_id: 'm', candidate_id: 'c', phase: 'merge', started_at: 'now', finished_at: null, duration_ms: null, agent_id: null, session_id: null, provider_id: null, retries: 0, token_usage: 'unknown', cost_usd: 'unknown', timeout_seconds: null, outcome: 'blocked', error_sanitized: null, human_touch_count: 0 };
    const { rerender } = render(<TelemetryCard phases={[p]} />); expect(screen.getByText(/duração unknown/)).toBeInTheDocument();
    rerender(<TelemetryCard phases={[{ ...p, duration_ms: 0, cost_usd: 0 }]} />); expect(screen.getByText(/duração 0 ms/)).toBeInTheDocument();
  });
  it.each(['success', 'failure', 'cancelled', 'timed_out', 'unknown'] as const)('renders CI conclusion %s and sanitized logs', conclusion => {
    render(<CiStatusCard busy={false} onRefresh={vi.fn()} runs={[{ id: 'run', pr_record_id: 'pr', commit_sha: 'head', name: 'Tests', status: 'completed', conclusion, run_url: 'https://github.com/org/repo/actions/runs/1', logs_sanitized: 'token=do-not-display', started_at: null, completed_at: null }]} />);
    expect(screen.getByText(`completed · ${conclusion}`)).toBeInTheDocument(); expect(screen.getByText('token=[mascarado]')).toBeInTheDocument();
    expect(screen.getByRole('link')).toHaveAttribute('rel', 'noreferrer noopener');
  });
  it.each(['javascript:alert(1)', 'https://user:pass@example.com', 'https://example.com?token=hidden', 'http://example.com'])('rejects unsafe link %s', url => {
    render(<ExternalLink url={url}>Open</ExternalLink>); expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });
  it('submits only configurable binding fields', async () => {
    const save = vi.fn(); render(<RemoteBindingCard binding={null} projectId="p1" busy={false} onSave={save} />);
    await userEvent.click(screen.getByRole('button', { name: 'Configurar remote' })); await userEvent.type(screen.getByLabelText('URL do repositório (sem credenciais)'), 'https://github.com/org/repo.git'); await userEvent.click(screen.getByRole('button', { name: 'Salvar binding' }));
    expect(save).toHaveBeenCalledWith({ project_id: 'p1', provider: 'github', remote_name: 'origin', remote_url: 'https://github.com/org/repo.git', target_branch: 'main', default_merge_method: 'squash' });
  });
  it('shows post-merge evidence and completed revert', () => {
    render(<RollbackCard busy={false} onPropose={vi.fn()} postMerge={{ id: 'pm', candidate_id: 'c', target_sha_observed: 'merged-sha', checks_run: [{ name: 'smoke', passed: false, detail: 'regression' }], status: 'failed', verified_at: 'now' }} plan={{ id: 'r', candidate_id: 'c', merge_commit_sha: 'merged-sha', strategy: 'revert_pr', revert_branch: 'revert/delivery', revert_pr_url: 'https://github.com/org/repo/pull/2', status: 'completed', created_at: 'now' }} />);
    expect(screen.getByText('Revert: revert_pr · completed')).toBeInTheDocument(); expect(screen.getByRole('link', { name: /Abrir PR de revert/ })).toBeInTheDocument();
  });
  it('redacts credential-bearing URLs and authorization strings', () => {
    expect(safeText('https://name:password@example.com Bearer value secret=private')).toBe('https://[mascarado]@example.com Bearer [mascarado] secret=[mascarado]');
  });
});

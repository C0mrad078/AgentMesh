import { describe, expect, it, vi } from 'vitest';
import { deliveryApi as api } from '../deliveryApi';
import { invokeBridge } from '../bridge';
vi.mock('../bridge', () => ({ invokeBridge: vi.fn().mockResolvedValue({}) }));
describe('Delivery API contract', () => {
  it('maps all 16 commands to the exact bridge namespace and snake_case payloads', async () => {
    const cases: [() => Promise<unknown>, string, Record<string, unknown>][] = [
      [() => api.create('m', 'p'), 'candidate.create', { mission_id: 'm', project_id: 'p' }],
      [() => api.get('c'), 'candidate.get', { candidate_id: 'c' }],
      [() => api.list({ project_id: 'p' }), 'candidate.list', { project_id: 'p' }],
      [() => api.preflight('c'), 'preflight.run', { candidate_id: 'c' }],
      [() => api.binding('p'), 'binding.get', { project_id: 'p' }],
      [() => api.saveBinding({ project_id: 'p', provider: 'git', remote_url: 'url' }), 'binding.save', { project_id: 'p', provider: 'git', remote_url: 'url' }],
      [() => api.approve('c', 'push', 'approved', 'human', 'reviewed'), 'approval.submit', { candidate_id: 'c', action: 'push', decision: 'approved', actor: 'human', reason: 'reviewed' }],
      [() => api.push('c', 'key'), 'remote.push', { candidate_id: 'c', idempotency_key: 'key' }],
      [() => api.createPr('c', 'key'), 'pr.create', { candidate_id: 'c', idempotency_key: 'key' }],
      [() => api.updatePr('c', 'key'), 'pr.update', { candidate_id: 'c', idempotency_key: 'key' }],
      [() => api.ci('c'), 'ci.status', { candidate_id: 'c' }],
      [() => api.assignFix('c', 'f', 'a'), 'ci.assign_fix', { candidate_id: 'c', finding_id: 'f', agent_id: 'a' }],
      [() => api.merge('c', 'key', 'squash'), 'merge.execute', { candidate_id: 'c', idempotency_key: 'key', merge_method: 'squash' }],
      [() => api.proposeRollback('c', 'reason'), 'rollback.propose', { candidate_id: 'c', reason: 'reason' }],
      [() => api.rollback('c', 'key'), 'rollback.execute', { candidate_id: 'c', idempotency_key: 'key' }],
      [() => api.telemetry({ candidate_id: 'c' }), 'telemetry.list', { candidate_id: 'c' }],
    ];
    for (const [call, command, payload] of cases) { await call(); expect(invokeBridge).toHaveBeenLastCalledWith(`delivery.${command}`, payload); }
  });
});

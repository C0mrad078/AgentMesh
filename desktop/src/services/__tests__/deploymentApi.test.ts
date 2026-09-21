import { describe, expect, it, vi } from 'vitest';
import { deploymentApi } from '@/services/deploymentApi';
import { invokeBridge } from '@/services/bridge';
vi.mock('@/services/bridge', () => ({ invokeBridge: vi.fn() }));

describe('deploymentApi', () => {
  it('maps every contract command to the bridge', async () => {
    vi.mocked(invokeBridge).mockResolvedValue({});
    await deploymentApi.listEnvironments('p'); await deploymentApi.getEnvironment('p', 'e');
    await deploymentApi.bindEnvironment({ project_id: 'p', environment_id: 'e', provider: 'github_actions', remote_url: 'https://github.com/a/b', repo_name: 'a/b', target_branch: 'main', workflow_file: 'deploy.yml', environment_name: 'development' });
    await deploymentApi.createRelease('p', 'dc'); await deploymentApi.getRelease('p', 'r'); await deploymentApi.listReleases('p', 10, 2); await deploymentApi.runPredeploy('p', 'r');
    await deploymentApi.submitApproval({ project_id: 'p', release_candidate_id: 'r', environment_id: 'e', action: 'deploy_development', decision: 'approved', actor_id: 'a', actor_role: 'operator' });
    await deploymentApi.executeRun('p', 'r', 'e', 'key'); await deploymentApi.getRun('p', 'run'); await deploymentApi.healthCheck('p', 'e', 'run'); await deploymentApi.requestPromotion('p', 'r', 'dev', 'staging'); await deploymentApi.executePromotion('p', 'pr', 'key'); await deploymentApi.proposeRollback('p', 'e', 'run'); await deploymentApi.executeRollback('p', 'plan', 'key'); await deploymentApi.reconcile('p');
    expect(vi.mocked(invokeBridge).mock.calls.map(call => call[0])).toEqual(['deployment.environment.list', 'deployment.environment.get', 'deployment.environment.bind', 'deployment.release.create', 'deployment.release.get', 'deployment.release.list', 'deployment.predeploy.run', 'deployment.approval.submit', 'deployment.run.execute', 'deployment.run.get', 'deployment.health.check', 'deployment.promote.request', 'deployment.promote.execute', 'deployment.rollback.propose', 'deployment.rollback.execute', 'deployment.recovery.reconcile']);
  });
  it('does not add optional fields when omitted', async () => { vi.mocked(invokeBridge).mockResolvedValue({}); await deploymentApi.listReleases('p'); expect(invokeBridge).toHaveBeenCalledWith('deployment.release.list', { project_id: 'p' }); });
});

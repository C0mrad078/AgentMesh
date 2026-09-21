import type { DeliveryCandidateDetail, DeliveryCandidateSummary } from '@/types/delivery';
export function detail(): DeliveryCandidateDetail {
  return {
    candidate: { id: 'candidate-1', mission_id: 'mission-1', project_id: 'project-1', version: 1, status: 'draft', current_snapshot_id: 'snapshot-1', target_remote_binding_id: 'binding-1', created_at: '2026-09-21', updated_at: '2026-09-21' },
    snapshot: { id: 'snapshot-1', candidate_id: 'candidate-1', version: 1, mission_id: 'mission-1', project_id: 'project-1', base_sha: 'base-sha', integration_sha: 'integration-sha', diff_hash: 'diff-hash', commits: [{ sha: 'commit-sha', message: 'Delivery feature', author: 'Engineer', timestamp: '2026-09-21' }], diff_stat: { files_changed: 1, insertions: 2, deletions: 1 }, tasks_summary: [{ key: 't1', title: 'Implement delivery', agent_id: 'agent-1', status: 'completed' }], reviews_summary: [{ reviewer_agent: 'reviewer-1', decision: 'approved', timestamp: '2026-09-21' }], resolved_conflicts_summary: [], quality_gates_summary: [{ profile_id: 'test', command: 'npm test', exit_code: 0, status: 'passed' }], known_risks: [], schema_version: 1, created_at: '2026-09-21' },
    remote_binding: { id: 'binding-1', project_id: 'project-1', provider: 'github', remote_name: 'origin', remote_url_sanitized: 'https://github.com/example/repo.git', owner: 'example', repository: 'repo', target_branch: 'main', auth_detected: true, auth_type: 'gh_cli', permissions: ['push'], branch_protections: { requires_pr: true }, default_merge_method: 'squash', last_verified_at: null },
    preflight: null, pull_request: null, ci_runs: [], ci_findings: [], approvals: [], pending_approvals: [], remote_operations: [], post_merge: null, rollback_plan: null, telemetry: [], internal_steps: [], recovery: { is_blocked: false, recovery_reason: null, suggested_action: null }, diff_files: [{ path: 'src/delivery.ts', status: 'added', additions: 2, deletions: 1 }], remote_sha: null,
  };
}
export function summary(d = detail()): DeliveryCandidateSummary {
  return { ...d.candidate, base_sha: d.snapshot.base_sha, integration_sha: d.snapshot.integration_sha, remote_sha: d.remote_sha, pr_number: null, pr_url: null, risk_level: 'low', has_pending_approvals: d.pending_approvals.length > 0 };
}

import type { Agent } from '@/types';
import type { MissionSnapshot } from '../types';
export const agent: Agent = {
  id: 'agent-1', name: 'Developer', description: 'Implementation specialist', provider: 'codex_cli', model: 'default',
  system_prompt: '', capabilities: [{ name: 'coding', description: 'Code' }], tools: [],
  permissions: { can_read_files: true, can_write_files: true, can_run_git: true, can_run_terminal: true, max_tokens_per_call: null },
  config: {}, active: true, role: 'worker', avatar: null, status: 'idle', preferred_backend: null,
  fallback_backend: null, memory_profile: {}, project_id: null, visual_profile: {}, team_ids: [],
};
export const snapshot: MissionSnapshot = {
  schema_version: 1,
  mission: { schema_version: 1, id: 'mission-1', project_id: 'project-1', request: 'Fix increment', status: 'planned', reason: 'Ready', current_plan_id: 'plan-1', result: '', created_at: '2026-09-20', updated_at: '2026-09-20' },
  plans: [{ id: 'plan-1', version: 1, summary: 'Fix and review', leader_session_id: 'session-1', choices: [{ agent_id: agent.id, role: 'worker', reason: 'coding; CLI connected' }], tasks: [], limitations: [] }],
  sessions: [{ id: 'session-1', agent_id: agent.id, project_id: 'project-1', provider_id: 'provider_openai', backend_type: 'subscription', account_id: null, task_id: null, worktree_id: null, external_session_id: 'cli-1', status: 'working', started_at: null, updated_at: '2026-09-20', finished_at: null, metadata: {}, created_at: '2026-09-20' }],
  assignments: [{ id: 'assignment-1', mission_id: 'mission-1', task_id: null, agent_id: agent.id, session_id: 'session-1', role: 'worker', reason: 'coding', active: true }],
  tasks: [],
  messages: [{ id: 'message-1', mission_id: 'mission-1', task_id: null, from_session_id: 'session-1', to_session_id: null, channel: 'team', message_type: 'review_challenge', content: 'Please cover empty inputs', artifact_ids: [], reply_to: null, timestamp: '2026-09-20', delivery_status: 'delivered' }],
  artifacts: [{ id: 'artifact-1', task_id: null, session_id: 'session-1', kind: 'diff', title: 'Real diff', content: '- value + 2\n+ value + 1', paths: ['increment.py'], command: [], exit_code: null }],
  reviews: [], instructions: [],
  events: [{ schema_version: 1, sequence: 1, mission_id: 'mission-1', entity_type: 'missions', entity_id: 'mission-1', timestamp: '2026-09-20', record: { schema_version: 1, status: 'planned' } }],
};

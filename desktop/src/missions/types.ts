import type { Session, Task } from '@/types';
export type MissionStatus = 'draft' | 'analyzing' | 'planned' | 'awaiting_approval' | 'running' | 'reviewing' | 'changes_requested' | 'testing' | 'blocked' | 'completed' | 'failed' | 'cancelled';
export interface Mission { schema_version: 1; id: string; project_id: string; request: string; status: MissionStatus; reason: string; current_plan_id: string | null; result: string; created_at: string; updated_at: string }
export interface Choice { agent_id: string; role: 'leader' | 'worker' | 'reviewer'; reason: string }
export interface MissionPlan { id: string; version: number; summary: string; leader_session_id: string; choices: Choice[]; tasks: { key: string; title: string; description: string; depends_on: string[]; acceptance: string[] }[]; limitations: string[] }
export interface Assignment extends Choice { id: string; mission_id: string; task_id: string | null; session_id: string; active: boolean }
export type MessageType = 'question' | 'answer' | 'context_share' | 'handoff' | 'review_request' | 'review_challenge' | 'changes_requested' | 'fix_response' | 'approval' | 'blocker' | 'human_input_required';
export interface AgentMessage { id: string; mission_id: string; task_id: string | null; from_session_id: string; to_session_id: string | null; channel: string; message_type: MessageType; content: string; artifact_ids: string[]; reply_to: string | null; timestamp: string; delivery_status: 'pending' | 'delivered' }
export interface Artifact { id: string; task_id: string | null; session_id: string | null; kind: 'diff' | 'report' | 'test' | 'decision' | 'log'; title: string; content: string; paths: string[]; command: string[]; exit_code: number | null }
export interface Review { id: string; task_id: string; reviewer_session_id: string; worker_session_id: string; verdict: 'approval' | 'changes_requested' | 'human_input_required'; justification: string; challenges: string[]; round: number }
export interface Instruction { id: string; content: string; disposition: 'pending' | 'context_share' | 'replan' | 'queued'; reason: string }
export interface MissionEvent { schema_version: 1; sequence: number; mission_id: string; entity_type: string; entity_id: string; timestamp: string; record: Mission | MissionPlan | Assignment | AgentMessage | Artifact | Review | Instruction | { schema_version: 1; status: string } }
export interface MissionSnapshot { schema_version: 1; mission: Mission; plans: MissionPlan[]; tasks: Task[]; sessions: Session[]; assignments: Assignment[]; messages: AgentMessage[]; artifacts: Artifact[]; reviews: Review[]; instructions: Instruction[]; events: MissionEvent[] }
export type MissionAction = 'analyze' | 'start' | 'pause' | 'cancel' | 'resume' | 'instruction' | 'include_agent' | 'reassign' | 'approve';
export interface CommandInput { action: MissionAction; content?: string; session_id?: string; task_id?: string; agent_id?: string }
export function isMissionEvent(value: unknown): value is MissionEvent {
  if (typeof value !== 'object' || value === null) return false;
  const e = value as Partial<MissionEvent>;
  return e.schema_version === 1 && typeof e.mission_id === 'string' && typeof e.sequence === 'number' && Number.isSafeInteger(e.sequence);
}

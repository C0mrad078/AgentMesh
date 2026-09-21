import { invokeBridge } from './bridge';
import type { DeliveryCandidateDetail, DeliveryCandidateSummary, RemoteRepositoryBinding, RemoteRepositoryBindingInput, DeliveryAction, DeliveryApproval, RemoteOperation, PreflightReport, PullRequestRecord, CIWorkflowRun, CIFailureFinding, RollbackPlan, PhaseTelemetry, MergeMethod } from '@/types/delivery';
export const deliveryApi = {
  create: (mission_id: string, project_id: string) => invokeBridge<DeliveryCandidateDetail>('delivery.candidate.create', { mission_id, project_id }),
  get: (candidate_id: string) => invokeBridge<DeliveryCandidateDetail>('delivery.candidate.get', { candidate_id }),
  list: (filters: { project_id?: string; mission_id?: string } = {}) => invokeBridge<DeliveryCandidateSummary[]>('delivery.candidate.list', filters),
  preflight: (candidate_id: string) => invokeBridge<PreflightReport>('delivery.preflight.run', { candidate_id }),
  binding: (project_id: string) => invokeBridge<RemoteRepositoryBinding>('delivery.binding.get', { project_id }),
  saveBinding: (input: RemoteRepositoryBindingInput) => invokeBridge<RemoteRepositoryBinding>('delivery.binding.save', { ...input }),
  approve: (candidate_id: string, action: DeliveryAction, decision: DeliveryApproval['decision'], actor: string, reason?: string) => invokeBridge<DeliveryApproval>('delivery.approval.submit', { candidate_id, action, decision, actor, reason }),
  push: (candidate_id: string, idempotency_key: string) => invokeBridge<RemoteOperation>('delivery.remote.push', { candidate_id, idempotency_key }),
  createPr: (candidate_id: string, idempotency_key: string) => invokeBridge<PullRequestRecord>('delivery.pr.create', { candidate_id, idempotency_key }),
  updatePr: (candidate_id: string, idempotency_key: string) => invokeBridge<PullRequestRecord>('delivery.pr.update', { candidate_id, idempotency_key }),
  ci: (candidate_id: string) => invokeBridge<CIWorkflowRun[]>('delivery.ci.status', { candidate_id }),
  assignFix: (candidate_id: string, finding_id: string, agent_id?: string) => invokeBridge<CIFailureFinding>('delivery.ci.assign_fix', { candidate_id, finding_id, agent_id }),
  merge: (candidate_id: string, idempotency_key: string, merge_method?: MergeMethod) => invokeBridge<RemoteOperation>('delivery.merge.execute', { candidate_id, idempotency_key, merge_method }),
  proposeRollback: (candidate_id: string, reason: string) => invokeBridge<RollbackPlan>('delivery.rollback.propose', { candidate_id, reason }),
  rollback: (candidate_id: string, idempotency_key: string) => invokeBridge<RemoteOperation>('delivery.rollback.execute', { candidate_id, idempotency_key }),
  telemetry: (filters: { candidate_id?: string; mission_id?: string }) => invokeBridge<PhaseTelemetry[]>('delivery.telemetry.list', filters),
};

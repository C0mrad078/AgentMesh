import { invokeBridge } from '@/services/bridge';
import type { ApprovalAction, DeploymentApprovalDTO, DeploymentBindingDTO, DeploymentBindingInput, DeploymentEnvironmentDetail, DeploymentEnvironmentSummary, DeploymentRecoveryStateDTO, DeploymentRollbackExecutionDTO, DeploymentRollbackPlanDTO, DeploymentRunDetail, HealthCheckResultDTO, PredeployReportDTO, PromotionRequestDTO, ReleaseCandidateDetail, ReleaseCandidateSummary } from '@/types/deployment';

export const deploymentApi = {
  listEnvironments: (project_id: string) => invokeBridge<DeploymentEnvironmentSummary[]>('deployment.environment.list', { project_id }),
  getEnvironment: (project_id: string, environment_id: string) => invokeBridge<DeploymentEnvironmentDetail>('deployment.environment.get', { project_id, environment_id }),
  bindEnvironment: (input: DeploymentBindingInput) => invokeBridge<DeploymentBindingDTO>('deployment.environment.bind', { ...input }),
  createRelease: (project_id: string, delivery_candidate_id: string) => invokeBridge<ReleaseCandidateDetail>('deployment.release.create', { project_id, delivery_candidate_id }),
  getRelease: (project_id: string, release_candidate_id: string) => invokeBridge<ReleaseCandidateDetail>('deployment.release.get', { project_id, release_candidate_id }),
  listReleases: (project_id: string, limit?: number, offset?: number) => invokeBridge<ReleaseCandidateSummary[]>('deployment.release.list', { project_id, ...(limit === undefined ? {} : { limit }), ...(offset === undefined ? {} : { offset }) }),
  runPredeploy: (project_id: string, release_candidate_id: string) => invokeBridge<PredeployReportDTO>('deployment.predeploy.run', { project_id, release_candidate_id }),
  submitApproval: (input: { project_id: string; release_candidate_id: string; environment_id: string; action: ApprovalAction; decision: 'approved' | 'rejected'; actor_id: string; actor_role: string; comment?: string }) => invokeBridge<DeploymentApprovalDTO>('deployment.approval.submit', input),
  executeRun: (project_id: string, release_candidate_id: string, environment_id: string, idempotency_key?: string) => invokeBridge<DeploymentRunDetail>('deployment.run.execute', { project_id, release_candidate_id, environment_id, ...(idempotency_key ? { idempotency_key } : {}) }),
  getRun: (project_id: string, deployment_run_id: string) => invokeBridge<DeploymentRunDetail>('deployment.run.get', { project_id, deployment_run_id }),
  healthCheck: (project_id: string, environment_id: string, deployment_run_id?: string) => invokeBridge<HealthCheckResultDTO>('deployment.health.check', { project_id, environment_id, ...(deployment_run_id ? { deployment_run_id } : {}) }),
  requestPromotion: (project_id: string, release_candidate_id: string, from_environment_id: string, to_environment_id: string) => invokeBridge<PromotionRequestDTO>('deployment.promote.request', { project_id, release_candidate_id, from_environment_id, to_environment_id }),
  executePromotion: (project_id: string, promotion_request_id: string, idempotency_key?: string) => invokeBridge<DeploymentRunDetail>('deployment.promote.execute', { project_id, promotion_request_id, ...(idempotency_key ? { idempotency_key } : {}) }),
  proposeRollback: (project_id: string, environment_id: string, deployment_run_id?: string) => invokeBridge<DeploymentRollbackPlanDTO>('deployment.rollback.propose', { project_id, environment_id, ...(deployment_run_id ? { deployment_run_id } : {}) }),
  executeRollback: (project_id: string, rollback_plan_id: string, idempotency_key?: string) => invokeBridge<DeploymentRollbackExecutionDTO>('deployment.rollback.execute', { project_id, rollback_plan_id, ...(idempotency_key ? { idempotency_key } : {}) }),
  reconcile: (project_id: string) => invokeBridge<DeploymentRecoveryStateDTO>('deployment.recovery.reconcile', { project_id }),
};

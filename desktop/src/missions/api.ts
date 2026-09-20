import { invokeBridge } from '@/services/bridge';
import type { CommandInput, Mission, MissionSnapshot } from './types';
export const missionsApi = {
  list: (project_id: string) => invokeBridge<Mission[]>('mission.list', { project_id }),
  get: (mission_id: string) => invokeBridge<MissionSnapshot>('mission.get', { mission_id }),
  create: (project_id: string, request: string, command_id: string) => invokeBridge<Mission>('mission.create', { project_id, request, command_id }),
  command: (mission_id: string, input: CommandInput, command_id: string) => invokeBridge<Mission>('mission.command', { mission_id, ...input, command_id }),
};

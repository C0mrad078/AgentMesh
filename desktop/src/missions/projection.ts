import type { Edge, Node } from '@xyflow/react';
import type { Agent } from '@/types';
import type { MissionSnapshot } from './types';
export type EntityKind = 'mission' | 'agent' | 'session' | 'task' | 'message' | 'artifact';
export interface EntitySelection { kind: EntityKind; id: string }
export type WorkspaceNode = Node<{ label: string; kind: EntityKind; entityId: string }>;
/** Pure materialized event projection; geometry carries no business rules. */
export function projectWorkspace(snapshot: MissionSnapshot | null, agents: Agent[]) {
  const nodes: WorkspaceNode[] = [];
  const edges: Edge[] = [];
  const add = (kind: EntityKind, id: string, label: string, x: number, y: number) => {
    nodes.push({ id, data: { kind, entityId: id, label }, position: { x, y },
      ariaLabel: label, style: { width: 220, background: '#172334', color: '#ecf4fc', borderColor: '#4a687f', borderRadius: 12, padding: 14 } });
  };
  const relate = (id: string, source: string, target: string, label: string, active = false) => {
    edges.push({ id, source, target, label, animated: active, style: { stroke: '#65b5bc' },
      labelStyle: { fill: '#d0edf0' }, labelBgStyle: { fill: '#142030' } });
  };
  if (!snapshot) {
    agents.filter(a => a.active).forEach((a, i) => add('agent', a.id, `${a.name}\n${a.role || a.capabilities.map(c => c.name).join(', ')}`, (i % 3) * 290, Math.floor(i / 3) * 150));
    return { nodes, edges };
  }
  const { mission, sessions, assignments, tasks, messages, artifacts } = snapshot;
  add('mission', mission.id, `${mission.request.slice(0, 70)}\n${mission.status}`, 340, 0);
  const involved = agents.filter(a => assignments.some(as => as.agent_id === a.id));
  involved.forEach((agent, i) => {
    add('agent', agent.id, `${agent.name}\n${agent.provider}`, i * 300, 170);
    relate(`supervise-${agent.id}`, mission.id, agent.id, assignments.find(a => a.agent_id === agent.id)?.role ?? 'equipe');
  });
  sessions.forEach((session, i) => {
    const index = involved.findIndex(a => a.id === session.agent_id);
    const row = sessions.slice(0, i).filter(s => s.agent_id === session.agent_id).length;
    add('session', session.id, `Sessão ${session.id.slice(-6)}\n${session.status}`, Math.max(0, index) * 300, 340 + row * 150);
    relate(`identity-${session.id}`, session.agent_id, session.id, 'sessão', session.status === 'working');
  });
  const bottom = 520 + sessions.length * 65;
  tasks.forEach((task, i) => {
    add('task', task.id, `${task.title}\n${task.status}`, i * 280, bottom);
    assignments.filter(a => a.task_id === task.id && a.active).forEach(a => relate(a.id, a.session_id, task.id, a.role));
  });
  messages.slice(-8).forEach((msg, i) => {
    add('message', msg.id, `${msg.message_type}\n${msg.content.slice(0, 65)}`, (i % 4) * 275, bottom + 190 + Math.floor(i / 4) * 140);
    relate(`from-${msg.id}`, msg.from_session_id, msg.id, msg.delivery_status);
    if (msg.to_session_id) relate(`to-${msg.id}`, msg.id, msg.to_session_id, 'contexto');
  });
  artifacts.filter(a => a.kind !== 'log').slice(-4).forEach((artifact, i) => {
    add('artifact', artifact.id, `${artifact.kind}: ${artifact.title}`, i * 275, bottom + 540);
    relate(`artifact-${artifact.id}`, artifact.task_id ?? artifact.session_id ?? mission.id, artifact.id, 'evidência');
  });
  return { nodes, edges };
}

import { describe, expect, it } from 'vitest';
import { projectWorkspace } from '../projection';
import { isMissionEvent } from '../types';
import { agent, snapshot } from './fixtures';
describe('persistent collaboration projection', () => {
  it('separates identity, session, mission, message and artifact', () => {
    const { nodes, edges } = projectWorkspace(snapshot, [agent]);
    expect(nodes.map(n => n.data.kind)).toEqual(['mission', 'agent', 'session', 'message', 'artifact']);
    expect(edges.some(e => e.source === agent.id && e.target === 'session-1')).toBe(true);
    expect(edges.every(e => nodes.some(n => n.id === e.source) && nodes.some(n => n.id === e.target))).toBe(true);
  });
  it('shows available agents without inventing sessions or activity', () => {
    const { nodes, edges } = projectWorkspace(null, [agent]);
    expect(nodes).toHaveLength(1);
    expect(nodes[0].data.kind).toBe('agent');
    expect(edges).toEqual([]);
  });
  it('rejects unknown event schema and renders status from persistence', () => {
    expect(isMissionEvent(snapshot.events[0])).toBe(true);
    expect(isMissionEvent({ ...snapshot.events[0], schema_version: 2 })).toBe(false);
    const changed = { ...snapshot, sessions: snapshot.sessions.map(s => ({ ...s, status: 'interrupted' as const })) };
    expect(projectWorkspace(changed, [agent]).nodes.find(n => n.id === 'session-1')?.data.label).toContain('interrupted');
  });
});

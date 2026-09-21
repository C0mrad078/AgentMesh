import type { PhaseTelemetry } from '@/types/delivery';
import { Panel, Evidence } from './Panel';
export function TelemetryCard({ phases }: { phases: PhaseTelemetry[] }) {
  return <Panel title="Telemetria por fase">{!phases.length && <p>Sem telemetria registrada.</p>}
    {phases.map(p => <details key={p.id}><summary>{p.phase} · {p.outcome} · duração {p.duration_ms === null ? 'unknown' : `${p.duration_ms} ms`}</summary>
      <dl className="delivery-facts"><dt>Início / fim</dt><dd>{p.started_at} / {p.finished_at ?? 'unknown'}</dd><dt>Agent / session / provider</dt><dd>{p.agent_id ?? 'unknown'} / {p.session_id ?? 'unknown'} / {p.provider_id ?? 'unknown'}</dd><dt>Retries</dt><dd>{p.retries}</dd><dt>Custo USD</dt><dd>{p.cost_usd}</dd><dt>Timeout (s)</dt><dd>{p.timeout_seconds ?? 'unknown'}</dd><dt>Intervenções humanas</dt><dd>{p.human_touch_count}</dd></dl><Evidence value={p.token_usage} />{p.error_sanitized && <Evidence value={p.error_sanitized} />}
    </details>)}
  </Panel>;
}

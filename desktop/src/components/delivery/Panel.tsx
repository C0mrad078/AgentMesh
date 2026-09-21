import type { ReactNode } from 'react';
import { safeText, safeUrl } from './presentation';
export function Panel({ title, children }: { title: string; children: ReactNode }) {
  return <section className="delivery-panel" aria-label={title}><h2>{title}</h2>{children}</section>;
}
export function Evidence({ value }: { value: unknown }) { return <pre className="delivery-evidence">{safeText(typeof value === 'object' && value !== null ? JSON.stringify(value, null, 2) : value)}</pre>; }
export function ExternalLink({ url, children }: { url: string | null; children: ReactNode }) {
  const href = safeUrl(url);
  return href ? <a href={href} target="_blank" rel="noreferrer noopener">{children} ↗</a> : <span>Link indisponível</span>;
}

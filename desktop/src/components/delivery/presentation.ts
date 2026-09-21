/** Defense in depth for display/copy. Backend remains responsible for sanitizing DTOs. */
export function safeText(value: unknown): string {
  return String(value ?? 'unknown')
    .replace(/(https?:\/\/)[^\s/@]+:[^\s/@]+@/gi, '$1[mascarado]@')
    .replace(/-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----/g, '[chave privada mascarada]')
    .replace(/("(?:token|password|secret|api[_-]?key)"\s*:\s*)"[^"]*"/gi, '$1"[mascarado]"')
    .replace(/\b(Bearer\s+)\S+/gi, '$1[mascarado]')
    .replace(/\b((?:token|password|secret|api[_-]?key)\s*[=:]\s*)[^\s,;]+/gi, '$1[mascarado]')
    .replace(/\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)\b/g, '[mascarado]');
}
export function safeUrl(value: string | null): string | undefined {
  if (!value) return;
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) return;
    return url.href;
  } catch { return; }
}
export const actionLabels = { push: 'Push da branch', pr_create: 'Criar PR', pr_update: 'Atualizar PR', merge: 'Merge', rollback: 'Executar revert' };

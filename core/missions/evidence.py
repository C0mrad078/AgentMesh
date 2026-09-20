"""Bounded, secret-redacted file evidence, including files Git does not track yet."""
from __future__ import annotations

import difflib
import hashlib

from core.missions.models import FileEvidence
from core.security.secret_scanner import SecretScanner
from core.tools.path_guard import resolve_safe_path
from core.tools.project_scanner import ProjectScanner


def snapshot_files(workspace: str) -> list[FileEvidence]:
    entries = ProjectScanner(workspace).scan(max_files=5001)
    if len(entries) > 5000:
        raise ValueError('Projeto excede 5000 arquivos auditáveis; limite explícito deste corte.')
    files = []
    remaining_text = 100000
    for entry in sorted(entries, key=lambda e: e.path):
        path = resolve_safe_path(workspace, entry.path)
        digest = hashlib.sha256()
        prefix = b''
        with path.open('rb') as stream:
            while chunk := stream.read(65536):
                digest.update(chunk)
                if len(prefix) < 32000:
                    prefix += chunk[:32000 - len(prefix)]
        text = ''
        if b'\x00' not in prefix:
            text = SecretScanner().redact(prefix.decode('utf-8', errors='replace'))[0][:remaining_text]
            remaining_text -= len(text)
        files.append(FileEvidence(path=entry.path, sha256=digest.hexdigest(), text=text,
                                  truncated=entry.size > len(text.encode('utf-8'))))
    return files


def describe_changes(before: list[FileEvidence], after: list[FileEvidence]) -> tuple[str, list[str]]:
    old, new = {f.path: f for f in before}, {f.path: f for f in after}
    changed = sorted(p for p in old.keys() | new.keys()
                     if p not in old or p not in new or old[p].sha256 != new[p].sha256)
    lines = ['Evidência capturada pelo backend antes/depois da tarefa (SHA-256).']
    for path in sorted(old.keys() | new.keys()):
        a, b = old.get(path), new.get(path)
        lines.append(f'{path}: {a.sha256 if a else "ausente"} → {b.sha256 if b else "ausente"}'
                     + (' [inalterado]' if path not in changed else ' [alterado]'))
        if path in changed:
            lines.extend(difflib.unified_diff((a.text if a else '').splitlines(),
                (b.text if b else '').splitlines(), fromfile=f'before/{path}', tofile=f'after/{path}', lineterm=''))
            if (a and a.truncated) or (b and b.truncated):
                lines.append('[Conteúdo parcial/binário; hash cobre arquivo completo.]')
    return '\n'.join(lines), changed

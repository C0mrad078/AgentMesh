"""Secret Scanner.

Runs over any text before it becomes part of an `AIRequest` (file content,
tool output, search results) or a persisted log/event -- never let a
credential leak to a model or into `execution_events`/logs. Pattern-based,
deliberately conservative (a few false positives redacted is a fine
trade-off; a real key leaking is not).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("openai_style_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("anthropic_style_key", re.compile(r"sk-ant-[A-Za-z0-9-]{20,}")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    (
        "generic_secret_assignment",
        re.compile(
            r"(?i)(api[_-]?key|secret|password|passwd|token|credential)"
            r"\s*[:=]\s*['\"]?[A-Za-z0-9/+_=.-]{8,}['\"]?"
        ),
    ),
]


@dataclass(frozen=True)
class SecretMatch:
    kind: str
    start: int
    end: int


class SecretScanner:
    def scan(self, text: str) -> list[SecretMatch]:
        matches: list[SecretMatch] = []
        for kind, pattern in _PATTERNS:
            for m in pattern.finditer(text):
                matches.append(SecretMatch(kind=kind, start=m.start(), end=m.end()))
        return matches

    def contains_secret(self, text: str) -> bool:
        return any(pattern.search(text) for _, pattern in _PATTERNS)

    def redact(self, text: str) -> tuple[str, list[SecretMatch]]:
        matches = self.scan(text)
        if not matches:
            return text, []
        # Merge overlapping matches (e.g. a generic assignment pattern and a
        # more specific key pattern both matching the same span) before
        # redacting, so we don't emit nested/duplicated placeholders.
        merged = _merge_overlapping(sorted(matches, key=lambda m: m.start))
        redacted = text
        for match in sorted(merged, key=lambda m: m.start, reverse=True):
            redacted = redacted[: match.start] + f"[REDACTED:{match.kind}]" + redacted[match.end :]
        return redacted, merged


def _merge_overlapping(matches: list[SecretMatch]) -> list[SecretMatch]:
    if not matches:
        return []
    merged = [matches[0]]
    for current in matches[1:]:
        last = merged[-1]
        if current.start <= last.end:
            if current.end > last.end:
                merged[-1] = SecretMatch(kind=last.kind, start=last.start, end=current.end)
            continue
        merged.append(current)
    return merged

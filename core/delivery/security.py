"""Validate identifiers before argv construction; redact before persistence."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from core.security.secret_scanner import SecretScanner
from core.utils.errors import ValidationError


def ref(value: str) -> str:
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,180}", value)
        or any(x in value for x in ("..", "//", "@{"))
        or any(p.startswith(".") or p.endswith(".lock") for p in value.split("/"))
        or value.endswith(("/", "."))
    ):
        raise ValidationError("Unsafe Git reference")
    return value


def sha(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValidationError("Invalid commit SHA")
    return value


def sanitize_url(value: str) -> str:
    if any(ord(c) < 32 for c in value) or "\\" in value:
        raise ValidationError("Invalid remote URL")
    scp = re.fullmatch(r"git@([A-Za-z0-9.-]+):([A-Za-z0-9_./-]+)", value)
    if scp:
        value = f"ssh://git@{scp[1]}/{scp[2]}"
    parsed = urlsplit(value)
    if parsed.scheme not in ("https", "ssh") or not parsed.hostname:
        raise ValidationError("Only HTTPS or SSH remotes are supported")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", parsed.hostname):
        raise ValidationError("Invalid remote host")
    path = parsed.path.rstrip("/")
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", path) or ".." in path:
        raise ValidationError("Invalid repository path")
    host = parsed.hostname.lower()
    if parsed.port:
        host += f":{parsed.port}"
    if parsed.scheme == "ssh":
        host = "git@" + host
    return urlunsplit((parsed.scheme, host, path, "", ""))


def clean(value: str) -> str:
    value = re.sub(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)",
        "[REDACTED:private_key]",
        value,
        flags=re.DOTALL,
    )
    value = re.sub(r'https?://[^\s<>"\']+', lambda m: _clean_url(m[0]), value)
    value = re.sub(r"(?i)(authorization\s*:\s*|bearer\s+)[^\s]+", r"\1[REDACTED]", value)
    return SecretScanner().redact(value)[0]


def _clean_url(value: str) -> str:
    try:
        p = urlsplit(value)
        host = p.hostname or ""
        if p.port:
            host += f":{p.port}"
        return urlunsplit((p.scheme, host, p.path, "", ""))
    except ValueError:
        return "[REDACTED:url]"


def clean_data(value: Any) -> Any:
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, list):
        return [clean_data(v) for v in value]
    if isinstance(value, dict):
        return {clean(str(k)): clean_data(v) for k, v in value.items()}
    return value


async def private_run(runner, argv, **kwargs):
    """Raw Git/CI evidence must not inherit an agent's stdout observer."""
    from core.utils.process_observer import process_observer

    token = process_observer.set(None)
    try:
        return await runner.run(argv, **kwargs)
    finally:
        process_observer.reset(token)

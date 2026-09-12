"""Strongly-typed parser for `codex exec --json`'s JSONL event stream.

The shapes below were captured from real, live invocations of the
installed Codex CLI (`codex-cli 0.154.0`), not guessed from documentation
-- see the four event kinds actually observed:

    {"type":"thread.started","thread_id":"..."}
    {"type":"turn.started"}
    {"type":"item.started"|"item.completed","item":{"id":...,"type":"agent_message","text":...}}
    {"type":"item.started"|"item.completed","item":{"id":...,"type":"command_execution","command":...,"aggregated_output":...,"exit_code":...,"status":...}}
    {"type":"item.started"|"item.completed","item":{"id":...,"type":"file_change","changes":[{"path":...,"kind":...}],"status":...}}
    {"type":"item.completed","item":{"id":...,"type":"error","message":...}}
    {"type":"turn.completed","usage":{"input_tokens":...,"cached_input_tokens":...,"cache_write_input_tokens":...,"output_tokens":...,"reasoning_output_tokens":...}}
    {"type":"turn.failed","error":{"message":...}}
    {"type":"error","message":...}

Critically, a hard failure (invalid model, provider error) still exits 0 --
`turn.failed`/a top-level `error` event is the only reliable failure
signal, never the process exit code alone. An unrecognized JSON line or
event type is skipped (logged, never raised): a future Codex CLI version
adding a new item type must not crash the adapter, only lose that one
detail.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from core.utils.logging import get_logger

logger = get_logger("providers.codex_events")


@dataclass(frozen=True)
class FileChange:
    path: str
    kind: str  # "add" | "delete" | "update" (as reported by Codex)


@dataclass(frozen=True)
class CommandExecution:
    command: str
    aggregated_output: str
    exit_code: int | None
    status: str


@dataclass(frozen=True)
class CodexTurnResult:
    thread_id: str | None = None
    final_message: str = ""
    file_changes: list[FileChange] = field(default_factory=list)
    commands: list[CommandExecution] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    failed: bool = False
    error_message: str | None = None


def parse_codex_jsonl(stdout: str) -> CodexTurnResult:
    thread_id: str | None = None
    messages: list[str] = []
    file_changes: list[FileChange] = []
    commands: list[CommandExecution] = []
    input_tokens = 0
    output_tokens = 0
    failed = False
    error_message: str | None = None

    for line in stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue  # e.g. "Reading additional input from stdin..." on stderr-adjacent noise
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("codex_event_not_json", extra={"context": {"line": line[:200]}})
            continue
        if not isinstance(event, dict):
            continue

        event_type = event.get("type")

        if event_type == "thread.started":
            thread_id = event.get("thread_id")

        elif event_type == "turn.failed":
            failed = True
            error_message = _extract_error_message(event.get("error"))

        elif event_type == "error":
            failed = True
            error_message = _extract_error_message(event) or error_message

        elif event_type == "item.completed":
            item = event.get("item")
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "agent_message":
                text = item.get("text")
                if isinstance(text, str):
                    messages.append(text)
            elif item_type == "command_execution":
                commands.append(CommandExecution(
                    command=str(item.get("command", "")),
                    aggregated_output=str(item.get("aggregated_output", "")),
                    exit_code=item.get("exit_code"),
                    status=str(item.get("status", "")),
                ))
            elif item_type == "file_change":
                for change in item.get("changes") or []:
                    if isinstance(change, dict) and "path" in change:
                        file_changes.append(FileChange(
                            path=str(change["path"]), kind=str(change.get("kind", "update")),
                        ))
            elif item_type == "error":
                failed = True
                error_message = str(item.get("message")) or error_message
            # Any other/future item type is intentionally ignored, not fatal.

        elif event_type == "turn.completed":
            usage = event.get("usage")
            if isinstance(usage, dict):
                input_tokens = int(usage.get("input_tokens") or 0)
                output_tokens = int(usage.get("output_tokens") or 0)

        # item.started and turn.started carry no information this parser
        # needs yet; intentionally not an `else: logger.warning(...)` for
        # every unrecognized type, since Codex is free to add progress
        # events without that being a parsing problem.

    return CodexTurnResult(
        thread_id=thread_id,
        final_message=messages[-1] if messages else "",
        file_changes=file_changes,
        commands=commands,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        failed=failed,
        error_message=error_message,
    )


def _extract_error_message(payload: object) -> str | None:
    if isinstance(payload, dict):
        message = payload.get("message")
        return str(message) if message is not None else None
    if isinstance(payload, str):
        return payload
    return None

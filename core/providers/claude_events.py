"""Strongly-typed parser for `claude --print --output-format stream-json
--verbose`'s event stream.

Shapes captured from real, live invocations of the installed Claude Code
CLI (`2.1.269`), not guessed from documentation:

    {"type":"system","subtype":"init",...}                      -- session start, noisy, ignored
    {"type":"system","subtype":"hook_started"|...}               -- hook chatter, ignored
    {"type":"rate_limit_event",...}                               -- ignored
    {"type":"assistant","message":{"content":[{"type":"text","text":...}]},...}
    {"type":"assistant","message":{"content":[{"type":"tool_use","id":...,"name":...,"input":{...}}]},...}
    {"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":...,"content":...}]},...}
    {"type":"result","subtype":"success"|...,"is_error":bool,"result":str,
     "total_cost_usd":float,"usage":{"input_tokens":...,"output_tokens":...},
     "session_id":str,"num_turns":int,"api_error_status":int|None}

Critically, `is_error: true` (an invalid model, an API 4xx) is reported
inside this final `result` object with the process still exiting 0 --
verified live -- so the exit code alone is never authoritative, exactly
like the Codex CLI (see `core.providers.codex_events`). A `--print
--output-format stream-json` run always ends with exactly one line where
`type == "result"`; that line alone carries content/usage/cost/success,
independent of whether any earlier `assistant`/`tool_use` lines were seen.

Unrecognized lines and event types are skipped, never fatal -- Claude Code
adds hook/telemetry event types across versions that this adapter has no
reason to understand.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from core.utils.logging import get_logger

logger = get_logger("providers.claude_events")

_FILE_WRITING_TOOLS = frozenset({"Write", "Edit", "NotebookEdit"})


@dataclass(frozen=True)
class ClaudeToolUse:
    name: str
    file_path: str | None


@dataclass(frozen=True)
class ClaudeTurnResult:
    session_id: str | None = None
    final_message: str = ""
    file_changes: list[ClaudeToolUse] = field(default_factory=list)
    all_tool_uses: list[ClaudeToolUse] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    num_turns: int = 0
    failed: bool = False
    error_message: str | None = None


def parse_claude_stream_json(stdout: str) -> ClaudeTurnResult:
    file_changes: list[ClaudeToolUse] = []
    all_tool_uses: list[ClaudeToolUse] = []
    result_line: dict | None = None

    for line in stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("claude_event_not_json", extra={"context": {"line": line[:200]}})
            continue
        if not isinstance(event, dict):
            continue

        event_type = event.get("type")

        if event_type == "result":
            result_line = event  # the last one wins if more than one ever appears

        elif event_type == "assistant":
            message = event.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = str(block.get("name", ""))
                    tool_input = block.get("input")
                    file_path = (
                        tool_input.get("file_path")
                        if isinstance(tool_input, dict) and isinstance(tool_input.get("file_path"), str)
                        else None
                    )
                    use = ClaudeToolUse(name=name, file_path=file_path)
                    all_tool_uses.append(use)
                    if name in _FILE_WRITING_TOOLS and file_path:
                        file_changes.append(use)

        # "system", "user" (tool_result), "rate_limit_event", and any
        # future event type carry nothing this parser needs yet.

    if result_line is None:
        return ClaudeTurnResult(
            file_changes=file_changes, all_tool_uses=all_tool_uses,
            failed=True, error_message="No terminal 'result' event was found in the CLI output.",
        )

    usage = result_line.get("usage")
    is_error = bool(result_line.get("is_error", False))
    return ClaudeTurnResult(
        session_id=result_line.get("session_id"),
        final_message=str(result_line.get("result") or ""),
        file_changes=file_changes,
        all_tool_uses=all_tool_uses,
        input_tokens=int(usage.get("input_tokens") or 0) if isinstance(usage, dict) else 0,
        output_tokens=int(usage.get("output_tokens") or 0) if isinstance(usage, dict) else 0,
        cost_usd=float(result_line.get("total_cost_usd") or 0.0),
        num_turns=int(result_line.get("num_turns") or 0),
        failed=is_error,
        error_message=str(result_line.get("result")) if is_error else None,
    )

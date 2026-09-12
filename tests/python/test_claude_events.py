"""Tests for `core.providers.claude_events`, using event fixtures captured
verbatim from real invocations of the installed Claude Code CLI (2.1.269)
-- not invented shapes."""

from __future__ import annotations

from core.providers.claude_events import ClaudeToolUse, parse_claude_stream_json

SIMPLE_SUCCESS = (
    '{"type":"system","subtype":"init","session_id":"s1","model":"claude-sonnet-5"}\n'
    '{"type":"assistant","message":{"content":[{"type":"text","text":"PROBE_OK"}]}}\n'
    '{"duration_api_ms":2588,"stop_reason":"end_turn","session_id":"s1","total_cost_usd":0.079,'
    '"usage":{"input_tokens":2,"output_tokens":9},"is_error":false,"num_turns":1,'
    '"subtype":"success","result":"PROBE_OK","type":"result"}\n'
)

WITH_TOOL_USE = (
    '{"type":"system","subtype":"init","session_id":"s2"}\n'
    '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t1","name":"Read",'
    '"input":{"file_path":"/tmp/sample.txt"}}]}}\n'
    '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"t1","content":"hello world"}]}}\n'
    '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t2","name":"Write",'
    '"input":{"file_path":"/tmp/out.txt","content":"DONE"}}]}}\n'
    '{"type":"assistant","message":{"content":[{"type":"text","text":"hello world"}]}}\n'
    '{"session_id":"s2","total_cost_usd":0.09,"usage":{"input_tokens":4,"output_tokens":10},'
    '"is_error":false,"num_turns":2,"result":"hello world","type":"result"}\n'
)

RESULT_IS_ERROR = (
    '{"type":"system","subtype":"init","session_id":"s3"}\n'
    '{"session_id":"s3","total_cost_usd":0.0,"usage":{"input_tokens":0,"output_tokens":0},'
    '"is_error":true,"api_error_status":404,"num_turns":1,'
    '"result":"There\'s an issue with the selected model.","type":"result"}\n'
)


def test_parses_a_simple_successful_turn() -> None:
    result = parse_claude_stream_json(SIMPLE_SUCCESS)
    assert result.session_id == "s1"
    assert result.final_message == "PROBE_OK"
    assert result.failed is False
    assert result.input_tokens == 2
    assert result.output_tokens == 9


def test_parses_tool_use_and_distinguishes_reads_from_file_changes() -> None:
    result = parse_claude_stream_json(WITH_TOOL_USE)
    assert result.final_message == "hello world"
    assert len(result.all_tool_uses) == 2  # Read + Write
    assert result.file_changes == [ClaudeToolUse(name="Write", file_path="/tmp/out.txt")]


def test_is_error_true_is_reported_even_though_the_process_exits_zero() -> None:
    # Real, verified Claude Code CLI behavior: an invalid-model 404 still
    # produces a `type: result` line with `is_error: true`, exit code 0.
    result = parse_claude_stream_json(RESULT_IS_ERROR)
    assert result.failed is True
    assert result.error_message is not None


def test_missing_terminal_result_line_is_treated_as_a_failure() -> None:
    result = parse_claude_stream_json('{"type":"system","subtype":"init"}\n')
    assert result.failed is True
    assert result.error_message is not None


def test_unrecognized_lines_and_event_types_are_skipped_not_fatal() -> None:
    stdout = (
        '{"type":"rate_limit_event","rate_limit_info":{}}\n'
        '{"type":"some.future.event","payload":{}}\n'
        "not even json {{{\n"
        '{"session_id":"s4","usage":{"input_tokens":1,"output_tokens":1},'
        '"is_error":false,"num_turns":1,"result":"still works","type":"result"}\n'
    )
    result = parse_claude_stream_json(stdout)
    assert result.final_message == "still works"
    assert result.failed is False


def test_empty_output_is_treated_as_a_failure_not_a_crash() -> None:
    result = parse_claude_stream_json("")
    assert result.failed is True

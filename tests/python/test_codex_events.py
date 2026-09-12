"""Tests for `core.providers.codex_events`, using JSONL fixtures captured
verbatim from real invocations of the installed Codex CLI (codex-cli
0.154.0) -- not invented shapes."""

from __future__ import annotations

from core.providers.codex_events import FileChange, parse_codex_jsonl

SIMPLE_SUCCESS = """\
{"type":"thread.started","thread_id":"01a0976e-9d1a-79e3-be95-4c8fee92f84a"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"PROBE_OK"}}
{"type":"turn.completed","usage":{"input_tokens":15179,"cached_input_tokens":12160,"cache_write_input_tokens":0,"output_tokens":7,"reasoning_output_tokens":0}}
"""

WITH_COMMAND_EXECUTION = """\
{"type":"thread.started","thread_id":"01a09772-0c98-7e82-8a9a-e202dec7872b"}
{"type":"turn.started"}
{"type":"item.started","item":{"id":"item_0","type":"command_execution","command":"/bin/zsh -lc 'cat sample.txt'","aggregated_output":"","exit_code":null,"status":"in_progress"}}
{"type":"item.completed","item":{"id":"item_0","type":"command_execution","command":"/bin/zsh -lc 'cat sample.txt'","aggregated_output":"hello world\\n","exit_code":0,"status":"completed"}}
{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"hello world"}}
{"type":"turn.completed","usage":{"input_tokens":30765,"cached_input_tokens":24320,"cache_write_input_tokens":0,"output_tokens":41,"reasoning_output_tokens":0}}
"""

WITH_FILE_CHANGE = """\
{"type":"thread.started","thread_id":"01a09772-59ec-7b12-a46c-3f61efddc8ce"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"I\\u2019ll create it."}}
{"type":"item.started","item":{"id":"item_1","type":"file_change","changes":[{"path":"/tmp/codex_probe/probe_output.txt","kind":"add"}],"status":"in_progress"}}
{"type":"item.completed","item":{"id":"item_1","type":"file_change","changes":[{"path":"/tmp/codex_probe/probe_output.txt","kind":"add"}],"status":"completed"}}
{"type":"item.completed","item":{"id":"item_2","type":"agent_message","text":"Created it."}}
{"type":"turn.completed","usage":{"input_tokens":30807,"cached_input_tokens":27392,"cache_write_input_tokens":0,"output_tokens":137,"reasoning_output_tokens":43}}
"""

TURN_FAILED = """\
{"type":"thread.started","thread_id":"01a09772-c411-7de3-813a-b8aaa423d805"}
{"type":"item.completed","item":{"id":"item_0","type":"error","message":"Model metadata for `bad-model` not found."}}
{"type":"turn.started"}
{"type":"error","message":"{\\"type\\":\\"error\\",\\"status\\":400,\\"error\\":{\\"type\\":\\"invalid_request_error\\",\\"message\\":\\"not supported\\"}}"}
{"type":"turn.failed","error":{"message":"{\\"type\\":\\"error\\",\\"status\\":400,\\"error\\":{\\"type\\":\\"invalid_request_error\\",\\"message\\":\\"not supported\\"}}"}}
"""


def test_parses_a_simple_successful_turn() -> None:
    result = parse_codex_jsonl(SIMPLE_SUCCESS)
    assert result.thread_id == "01a0976e-9d1a-79e3-be95-4c8fee92f84a"
    assert result.final_message == "PROBE_OK"
    assert result.failed is False
    assert result.input_tokens == 15179
    assert result.output_tokens == 7


def test_parses_command_execution_items() -> None:
    result = parse_codex_jsonl(WITH_COMMAND_EXECUTION)
    assert result.final_message == "hello world"
    assert len(result.commands) == 1
    assert result.commands[0].exit_code == 0
    assert "hello world" in result.commands[0].aggregated_output


def test_parses_file_change_items() -> None:
    result = parse_codex_jsonl(WITH_FILE_CHANGE)
    assert result.file_changes == [FileChange(path="/tmp/codex_probe/probe_output.txt", kind="add")]


def test_turn_failed_is_reported_even_though_the_process_exits_zero() -> None:
    # Real, verified Codex CLI behavior: an invalid-model 400 error still
    # exits 0 -- only the JSONL stream tells the truth.
    result = parse_codex_jsonl(TURN_FAILED)
    assert result.failed is True
    assert result.error_message is not None
    assert "not supported" in result.error_message


def test_unrecognized_lines_and_event_types_are_skipped_not_fatal() -> None:
    stdout = (
        "Reading additional input from stdin...\n"
        '{"type":"thread.started","thread_id":"t1"}\n'
        '{"type":"some.future.event","payload":{"whatever":true}}\n'
        '{"type":"item.completed","item":{"id":"i0","type":"future_item_type","blob":123}}\n'
        '{"type":"item.completed","item":{"id":"i1","type":"agent_message","text":"still works"}}\n'
        "not even json at all {{{\n"
    )
    result = parse_codex_jsonl(stdout)
    assert result.thread_id == "t1"
    assert result.final_message == "still works"
    assert result.failed is False


def test_empty_output_parses_to_an_empty_unfailed_result() -> None:
    result = parse_codex_jsonl("")
    assert result.failed is False
    assert result.final_message == ""
    assert result.thread_id is None

from __future__ import annotations

from core.learning.context_optimizer import ContextOptimizer


def _entry(step_id: str, *, files: list[str], used: list[str]) -> dict:
    return {"step_id": step_id, "files_count": len(files), "file_paths": files, "files_used": used}


def test_suggests_reducing_context_when_most_files_go_unused() -> None:
    entries = [
        _entry(f"s{i}", files=["a.py", "b.py", "c.py", "README.md"], used=["a.py"])
        for i in range(6)
    ]
    suggestions = ContextOptimizer().analyze(entries, category_by_step={f"s{i}": "debugging" for i in range(6)})
    assert len(suggestions) == 1
    assert suggestions[0].suggestion == "reduce"
    assert suggestions[0].task_category == "debugging"


def test_suggests_expanding_context_when_almost_everything_sent_is_used_and_volume_is_small() -> None:
    entries = [_entry(f"s{i}", files=["a.py"], used=["a.py"]) for i in range(6)]
    suggestions = ContextOptimizer().analyze(entries, category_by_step={f"s{i}": "debugging" for i in range(6)})
    assert len(suggestions) == 1
    assert suggestions[0].suggestion == "expand"


def test_no_suggestion_when_usage_ratio_is_balanced() -> None:
    entries = [
        _entry(f"s{i}", files=["a.py", "b.py", "c.py"], used=["a.py", "b.py"])
        for i in range(6)
    ]
    suggestions = ContextOptimizer().analyze(entries, category_by_step={f"s{i}": "debugging" for i in range(6)})
    assert suggestions == []


def test_below_minimum_sample_size_produces_no_suggestion() -> None:
    entries = [_entry("s1", files=["a.py", "b.py", "c.py"], used=[])]
    suggestions = ContextOptimizer().analyze(entries, category_by_step={"s1": "debugging"})
    assert suggestions == []


def test_categories_are_analyzed_independently() -> None:
    debugging_entries = [
        _entry(f"d{i}", files=["a.py", "b.py", "c.py"], used=["a.py"]) for i in range(6)
    ]
    docs_entries = [
        _entry(f"o{i}", files=["readme.md"], used=["readme.md"]) for i in range(6)
    ]
    category_by_step = {f"d{i}": "debugging" for i in range(6)} | {f"o{i}": "documentation" for i in range(6)}
    suggestions = ContextOptimizer().analyze(debugging_entries + docs_entries, category_by_step=category_by_step)
    categories = {s.task_category for s in suggestions}
    assert "debugging" in categories


def test_flags_a_rarely_used_file_extension() -> None:
    entries = [
        _entry(f"s{i}", files=["a.py", "notes.md"], used=["a.py"]) for i in range(6)
    ]
    suggestions = ContextOptimizer().analyze(entries, category_by_step={f"s{i}": "coding" for i in range(6)})
    assert len(suggestions) == 1
    assert ".md" in suggestions[0].rarely_used_extensions

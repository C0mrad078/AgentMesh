from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from core.database.connection import Database
from core.database.migrations import runner
from core.database.repositories.projects_repo import ProjectsRepository
from core.delivery.git_remote import GitRemote
from core.delivery.github_adapter import GitHubAdapter
from core.delivery.models import RemoteRepositoryBinding
from core.delivery.security import clean
from core.projects.models import ProjectCreate
from core.utils.errors import ValidationError
from core.utils.shell_runner import RunResult


@pytest.mark.parametrize("upgrade", [False, True])
async def test_delivery_migration_empty_upgrade_and_reopen(tmp_path, monkeypatch, upgrade):
    path = tmp_path / "migration.db"
    original = runner.discover_migrations
    if upgrade:
        monkeypatch.setattr(
            runner, "discover_migrations", lambda: [m for m in original() if m[0] < 20]
        )
        old = Database(path)
        await old.connect()
        project = await ProjectsRepository(old).create(ProjectCreate(name="preserved"))
        await old.close()
        monkeypatch.setattr(runner, "discover_migrations", original)
    db = Database(path)
    await db.connect()
    try:
        assert 20 in await runner.applied_versions(db.connection)
        assert not await db.fetch_all("PRAGMA foreign_key_check")
        assert await runner.run_migrations(db.connection) == []
        if upgrade:
            assert (await ProjectsRepository(db).get(project.id)).name == "preserved"
        tables = await db.fetch_all("SELECT name FROM sqlite_master WHERE name LIKE 'delivery_%'")
        assert len(tables) >= 10
    finally:
        await db.close()
    await db.connect()
    assert await db.quick_integrity_check()
    await db.close()


@pytest.fixture
def local_repo(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-b", "delivery-fixture")
    git("config", "user.name", "Delivery Test")
    git("config", "user.email", "delivery@example.invalid")
    (tmp_path / "base.txt").write_text("baseline\n")
    git("add", ".")
    git("commit", "-m", "baseline")
    base = git("rev-parse", "HEAD")
    (tmp_path / "new file.txt").write_text("delivery\n")
    git("add", ".")
    git("commit", "-m", "delivery")
    return tmp_path, base, git("rev-parse", "HEAD"), git


async def test_real_local_git_evidence_hash_commits_files_and_dirty_tree(local_repo):
    root, base, head, _ = local_repo
    adapter = GitRemote()
    evidence = await adapter.evidence(root, base, head)
    assert evidence["diff_hash"] == hashlib.sha256(evidence["diff"].encode()).hexdigest()
    assert evidence["commits"][0]["sha"] == head
    assert evidence["files"] == [
        {"path": "new file.txt", "status": "added", "additions": 1, "deletions": 0}
    ]
    assert await adapter.ancestor(root, base, head)
    assert not await adapter.ancestor(root, head, base)
    assert await adapter.clean_tree(root)
    (root / "untracked").write_text("dirty")
    assert not await adapter.clean_tree(root)


async def test_real_remote_config_sanitization_and_rewrite_block(local_repo):
    root, _, _, git = local_repo
    binding = RemoteRepositoryBinding(
        project_id="p", provider="github", remote_url_sanitized="https://github.com/team/repo.git"
    )
    git("remote", "add", "origin", "https://github.com/team/repo.git")
    adapter = GitRemote()
    await adapter.verify_remote(root, binding)
    git("remote", "set-url", "--push", "origin", "https://github.com/else/repo.git")
    with pytest.raises(ValidationError, match="differs"):
        await adapter.verify_remote(root, binding)
    git("remote", "set-url", "--push", "origin", "https://github.com/team/repo.git")
    git("config", "url.https://github.com/.insteadOf", "https://example.invalid/")
    with pytest.raises(ValidationError, match="rewrite"):
        await adapter.verify_remote(root, binding)


async def test_secret_deleted_before_head_still_detected_in_git_history(local_repo):
    root, base, _, git = local_repo
    secret = "ghp_" + "z" * 32
    (root / "temporary.txt").write_text(secret)
    git("add", ".")
    git("commit", "-m", "intermediate")
    (root / "temporary.txt").unlink()
    git("add", ".")
    git("commit", "-m", "remove intermediate file")
    evidence = await GitRemote().evidence(root, base, git("rev-parse", "HEAD"))
    assert secret not in evidence["diff"]
    assert secret in evidence["history"]
    assert secret not in clean(evidence["history"])


class RecordingRunner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.bodies = []

    async def run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        for flag in ("--body-file", "--input"):
            if flag in argv:
                self.bodies.append(
                    await asyncio.to_thread(Path(argv[argv.index(flag) + 1]).read_text)
                )
        response = self.responses.pop(0)
        if isinstance(response, RunResult):
            return response
        return RunResult(True, json.dumps(response), "", 0)


@pytest.fixture
def binding():
    return RemoteRepositoryBinding(
        project_id="p",
        provider="github",
        remote_url_sanitized="https://github.com/team/repo.git",
        owner="team",
        repository="repo",
    )


async def test_github_create_uses_body_file_and_reconciles_existing(tmp_path, binding):
    view = {"number": 9, "headRefOid": "b" * 40}
    runner = RecordingRunner(
        [[], RunResult(True, "https://github.com/team/repo/pull/9", "", 0), [{"number": 9}], view]
    )
    adapter = GitHubAdapter(runner)
    body = "Exact line one\nLiteral `shell` and $(substitution)\n"
    assert await adapter.create(tmp_path, binding, "agentmash/delivery-test", "Title", body) == view
    assert runner.bodies == [body]
    create = next(a for a, _ in runner.calls if a[:3] == ["gh", "pr", "create"])
    assert "--body-file" in create and "--body" not in create
    assert all("shell" not in kwargs for _, kwargs in runner.calls)
    existing_runner = RecordingRunner([[{"number": 9}], view])
    assert (
        await GitHubAdapter(existing_runner).create(
            tmp_path, binding, "agentmash/delivery-test", "Title", body
        )
        == view
    )
    assert not any("create" in a for a, _ in existing_runner.calls)


async def test_github_merge_sha_guard_no_admin_or_force(tmp_path, binding):
    runner = RecordingRunner([RunResult(True, "", "", 0), {"state": "MERGED"}])
    await GitHubAdapter(runner).merge(tmp_path, binding, 1, "b" * 40, "squash")
    argv = runner.calls[0][0]
    assert argv[-2:] == ["--match-head-commit", "b" * 40]
    assert "--squash" in argv
    assert "--admin" not in argv and "--force" not in argv


async def test_github_error_redacts_credentials(tmp_path, binding):
    secret = "ghp_" + "x" * 30
    runner = RecordingRunner(
        [
            RunResult(
                False, "", f"error https://user:{secret}@github.com/team/repo?token={secret}", 1
            )
        ]
    )
    with pytest.raises(ValidationError) as caught:
        await GitHubAdapter(runner).view(tmp_path, binding, 1)
    assert secret not in str(caught.value)


async def test_github_update_preserves_description_and_is_idempotent(tmp_path, binding):
    marker = "<!-- version:2 -->"
    runner = RecordingRunner([[[]], {"id": 1}, {"number": 1}])
    adapter = GitHubAdapter(runner)
    await adapter.update(tmp_path, binding, 1, marker, "Correction report")
    assert not any(a[:3] == ["gh", "pr", "edit"] for a, _ in runner.calls)
    assert json.loads(runner.bodies[0])["body"] == marker + "\nCorrection report"
    runner = RecordingRunner([[[{"body": marker + "\nCorrection report"}]], {"number": 1}])
    await GitHubAdapter(runner).update(tmp_path, binding, 1, marker, "Correction report")
    assert not any("--method" in a for a, _ in runner.calls)


async def test_git_push_only_delivery_refs_and_exact_sha(tmp_path, binding):
    class PushGit(GitRemote):
        def __init__(self):
            self.calls = []
            self.observations = [None, "b" * 40]

        async def remote_sha(self, *args):
            return self.observations.pop(0)

        async def run(self, root, args, **kwargs):
            self.calls.append(args)
            return ""

    adapter = PushGit()
    with pytest.raises(ValidationError, match="delivery"):
        await adapter.push(tmp_path, binding, "main", "b" * 40)
    await adapter.push(tmp_path, binding, "agentmash/delivery-1", "b" * 40)
    argv = adapter.calls[0]
    assert "push" == argv[0] and not any(a.startswith("--force") for a in argv)
    assert argv[-1] == "b" * 40 + ":refs/heads/agentmash/delivery-1"


def test_private_key_body_never_survives_masking():
    block = "-----BEGIN PRIVATE KEY-----\n" + "sensitive-body\n" + "-----END PRIVATE KEY-----"
    assert "sensitive-body" not in clean(block)


async def test_failed_ci_log_is_sanitized_before_return(tmp_path, binding):
    secret = "ghp_" + "q" * 30
    runner = RecordingRunner([RunResult(True, f"failure token={secret}", "", 0)])
    observation = {
        "statusCheckRollup": [
            {
                "name": "tests",
                "conclusion": "FAILURE",
                "detailsUrl": "https://github.com/team/repo/actions/runs/123/job/456",
            }
        ]
    }
    result = await GitHubAdapter(runner).failure_logs(tmp_path, binding, observation)
    assert secret not in result["statusCheckRollup"][0]["logs"]
    assert runner.calls[0][0] == ["gh", "run", "view", "123", "--repo", "team/repo", "--log-failed"]


async def test_git_remote_output_does_not_leak_to_agent_observer(local_repo):
    from core.utils.process_observer import process_observer

    root, base, head, _ = local_repo
    seen = []

    async def observer(event):
        seen.append(event)

    token = process_observer.set(observer)
    try:
        await GitRemote().evidence(root, base, head)
    finally:
        process_observer.reset(token)
    assert seen == []


async def test_observed_protection_and_supported_merge_methods(tmp_path, binding):
    runner = RecordingRunner(
        [
            RunResult(True, "authenticated", "", 0),
            {
                "permissions": {"pull": True, "push": True},
                "allow_merge_commit": True,
                "allow_squash_merge": True,
            },
            {"protected": True},
            {
                "required_status_checks": {
                    "contexts": ["test"],
                    "checks": [{"context": "security"}],
                    "strict": True,
                },
                "required_pull_request_reviews": {"required_approving_review_count": 2},
            },
        ]
    )
    result = await GitHubAdapter(runner).observe(tmp_path, binding)
    assert result["auth_detected"]
    assert result["branch_protections"]["merge_methods"] == ["merge", "squash"]
    assert result["branch_protections"]["required_status_checks"] == ["security", "test"]
    assert result["branch_protections"]["required_reviews"] == 2


async def test_pending_ci_null_conclusion_does_not_fetch_logs(tmp_path, binding):
    runner = RecordingRunner([])
    observation = {"statusCheckRollup": [{"name": "tests", "conclusion": None}]}
    assert await GitHubAdapter(runner).failure_logs(tmp_path, binding, observation) == observation
    assert not runner.calls


async def test_real_revert_in_isolated_worktree_preserves_original_branch(local_repo, binding):
    root, base, head, git = local_repo

    class LocalRevert(GitRemote):
        async def fetch(self, root, binding, branch):
            return head

    adapter = LocalRevert()
    path = root.parent / (root.name + "-revert")
    revert_sha = await adapter.revert(root, binding, head, "agentmash/delivery-revert", path)
    assert revert_sha != head
    assert await adapter.clean_tree(path)
    assert not (path / "new file.txt").exists()
    assert (path / "base.txt").read_text() == "baseline\n"
    assert git("rev-parse", "HEAD") == head
    assert await adapter.ancestor(path, head, revert_sha)
    assert (
        await adapter.revert(root, binding, head, "agentmash/delivery-revert", path) == revert_sha
    )

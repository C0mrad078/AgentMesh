from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from core.delivery.models import RemoteRepositoryBinding
from core.delivery.security import clean, clean_data, private_run, ref, sha
from core.utils.errors import ValidationError
from core.utils.shell_runner import ShellRunner, get_runner


class GitHubAdapter:
    def __init__(self, runner: ShellRunner | None = None) -> None:
        self.runner = runner or get_runner()

    def repo(self, binding: RemoteRepositoryBinding) -> str:
        if (
            binding.provider != "github"
            or urlsplit(binding.remote_url_sanitized).hostname != "github.com"
        ):
            raise ValidationError("GitHub.com binding required for PR/CI operations")
        if not binding.owner or not binding.repository:
            raise ValidationError("Missing GitHub owner/repository")
        return f"{ref(binding.owner)}/{ref(binding.repository)}"

    async def run(self, root: Path, args: list[str], *, json_result: bool = True) -> Any:
        result = await private_run(
            self.runner,
            ["gh", *args],
            cwd=root,
            timeout=120,
            env={"GH_PROMPT_DISABLED": "1", "GH_PAGER": "cat"},
        )
        if not result.success:
            raise ValidationError(
                f"GitHub {args[0]} failed (exit {result.returncode}): {clean(result.stderr)[:500]}"
            )
        if "[output truncated" in result.stdout:
            raise ValidationError("GitHub response exceeds capture limit")
        if not json_result:
            return clean(result.stdout)
        try:
            return clean_data(json.loads(result.stdout))
        except ValueError:
            raise ValidationError("Invalid GitHub response") from None

    async def observe(self, root: Path, binding: RemoteRepositoryBinding) -> dict[str, Any]:
        repository = self.repo(binding)
        await self.run(root, ["auth", "status", "--hostname", "github.com"], json_result=False)
        info = await self.run(root, ["api", f"repos/{repository}"])
        branch = await self.run(
            root, ["api", f"repos/{repository}/branches/{quote(binding.target_branch, safe='')}"]
        )
        protections: dict[str, Any] = {
            "requires_pr": True,
            "protected": branch.get("protected", False),
            "required_status_checks": [],
            "strict": False,
        }
        if branch.get("protected"):
            # Fail closed if protections cannot be observed; never infer absence from 403/404.
            raw = await self.run(
                root,
                [
                    "api",
                    f"repos/{repository}/branches/{quote(binding.target_branch, safe='')}/protection",
                ],
            )
            checks = raw.get("required_status_checks") or {}
            protections.update(
                required_status_checks=sorted(
                    set(checks.get("contexts", []))
                    | {c["context"] for c in checks.get("checks", [])}
                ),
                strict=checks.get("strict", False),
                required_reviews=(raw.get("required_pull_request_reviews") or {}).get(
                    "required_approving_review_count", 0
                ),
            )
        protections["merge_methods"] = [
            m
            for m in ("merge", "squash", "rebase")
            if info.get("allow_merge_commit" if m == "merge" else f"allow_{m}_merge")
        ]
        return {
            "auth_detected": True,
            "auth_type": "gh_cli",
            "permissions": [k for k, v in info.get("permissions", {}).items() if v],
            "branch_protections": protections,
        }

    async def view(
        self, root: Path, binding: RemoteRepositoryBinding, number: int
    ) -> dict[str, Any]:
        if number <= 0:
            raise ValidationError("Invalid PR number")
        return await self.run(
            root,
            [
                "pr",
                "view",
                str(number),
                "--repo",
                self.repo(binding),
                "--json",
                "id,number,url,title,body,headRefOid,baseRefOid,headRefName,baseRefName,state,isCrossRepository,isDraft,mergeStateStatus,reviewDecision,statusCheckRollup,mergeCommit",
            ],
        )

    async def find(
        self, root: Path, binding: RemoteRepositoryBinding, branch: str
    ) -> dict[str, Any] | None:
        rows = await self.run(
            root,
            [
                "pr",
                "list",
                "--repo",
                self.repo(binding),
                "--head",
                ref(branch),
                "--base",
                ref(binding.target_branch),
                "--state",
                "all",
                "--json",
                "number",
                "--limit",
                "100",
            ],
        )
        if len(rows) > 1:
            raise ValidationError("Multiple PRs match delivery branch; human intervention required")
        return await self.view(root, binding, rows[0]["number"]) if rows else None

    async def create(
        self, root: Path, binding: RemoteRepositoryBinding, branch: str, title: str, body: str
    ) -> dict[str, Any]:
        existing = await self.find(root, binding, branch)
        if existing:
            return existing
        # Body file avoids shell interpolation and platform command-length limits.
        with tempfile.TemporaryDirectory(prefix="agentmash-pr-") as directory:
            path = Path(directory) / "body.md"
            path.write_text(clean(body), encoding="utf-8")
            await self.run(
                root,
                [
                    "pr",
                    "create",
                    "--repo",
                    self.repo(binding),
                    "--head",
                    ref(branch),
                    "--base",
                    ref(binding.target_branch),
                    "--title",
                    clean(title),
                    "--body-file",
                    str(path),
                ],
                json_result=False,
            )
        created = await self.find(root, binding, branch)
        if not created:
            raise ValidationError("PR creation uncertain; retry to reconcile")
        return created

    async def merge(
        self, root: Path, binding: RemoteRepositoryBinding, number: int, head: str, method: str
    ) -> dict[str, Any]:
        if method not in ("merge", "squash", "rebase"):
            raise ValidationError("Unsupported merge method")
        await self.run(
            root,
            [
                "pr",
                "merge",
                str(number),
                "--repo",
                self.repo(binding),
                f"--{method}",
                "--match-head-commit",
                sha(head),
            ],
            json_result=False,
        )
        return await self.view(root, binding, number)

    async def update(
        self, root: Path, binding: RemoteRepositoryBinding, number: int, marker: str, body: str
    ) -> dict[str, Any]:
        # Preserve the complete human-authored PR description. Add a separately approved
        # version report; reconcile its marker before writing after a retry.
        endpoint = f"repos/{self.repo(binding)}/issues/{number}/comments"
        pages = await self.run(root, ["api", endpoint, "--paginate", "--slurp"])
        if not any(marker in comment.get("body", "") for page in pages for comment in page):
            with tempfile.TemporaryDirectory(prefix="agentmash-pr-update-") as directory:
                path = Path(directory) / "comment.json"
                path.write_text(json.dumps({"body": marker + "\n" + clean(body)}), encoding="utf-8")
                await self.run(root, ["api", endpoint, "--method", "POST", "--input", str(path)])
        return await self.view(root, binding, number)

    async def failure_logs(
        self, root: Path, binding: RemoteRepositoryBinding, observation: dict[str, Any]
    ) -> dict[str, Any]:
        import re

        cache: dict[str, str] = {}
        for check in observation.get("statusCheckRollup") or []:
            if (check.get("conclusion") or "").upper() not in ("FAILURE", "TIMED_OUT", "CANCELLED"):
                continue
            link = str(check.get("detailsUrl") or "")
            match = re.fullmatch(
                r"https://github.com/"
                + re.escape(self.repo(binding))
                + r"/actions/runs/([0-9]+)(?:/job/[0-9]+)?",
                link,
            )
            if not match:
                continue
            run_id = match[1]
            if run_id not in cache:
                try:
                    cache[run_id] = await self.run(
                        root,
                        ["run", "view", run_id, "--repo", self.repo(binding), "--log-failed"],
                        json_result=False,
                    )
                except ValidationError:
                    cache[run_id] = (
                        "CI logs unavailable; inspect provider permissions or log retention"
                    )
            check["logs"] = cache[run_id]
        return observation

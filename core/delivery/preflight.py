from __future__ import annotations

from pathlib import Path
from typing import Any

from core.delivery.git_remote import GitRemote
from core.delivery.models import DeliveryCandidate, DeliverySnapshot, PreflightReport
from core.security.secret_scanner import SecretScanner


async def scan_evidence(
    git: GitRemote, root: Path, snapshot: DeliverySnapshot, evidence: dict[str, Any]
) -> tuple[list[dict], list[dict], list[str]]:
    scanner = SecretScanner()
    findings: list[dict] = []
    large: list[dict] = []
    special: list[str] = []
    for label in ("diff", "history"):
        text = evidence[label]
        for match in scanner.scan(text):
            findings.append(
                {
                    "file_path": f"[{label}]",
                    "rule_id": match.kind,
                    "masked_sample": "[REDACTED]",
                    "line_number": text.count("\n", 0, match.start) + 1,
                }
            )
    for file in evidence["files"]:
        path = file["path"]
        lower = path.lower()
        if any(t in lower for t in ("migration", "lock", "generated", ".snap")):
            special.append(path)
        if lower.endswith((".pem", ".key", ".p12", ".pfx")) or Path(lower).name in (
            ".env",
            "credentials",
            "id_rsa",
        ):
            findings.append(
                {
                    "file_path": path,
                    "rule_id": "credential_file",
                    "masked_sample": "[REDACTED]",
                    "line_number": 1,
                }
            )
        if file["status"] == "deleted":
            continue
        size, content = await git.blob(root, snapshot.integration_sha, path)
        if size > 1024 * 1024 or path in evidence["binary"] or "\x00" in content:
            large.append({"file_path": path, "size_bytes": size})
        for match in scanner.scan(content):
            findings.append(
                {
                    "file_path": path,
                    "rule_id": match.kind,
                    "masked_sample": "[REDACTED]",
                    "line_number": content.count("\n", 0, match.start) + 1,
                }
            )
    return findings, large, special


def report(
    candidate: DeliveryCandidate,
    *,
    remote: bool,
    base: bool,
    clean: bool,
    gates: bool,
    findings: list[dict],
    large: list[dict],
    special: list[str],
    errors: list[str],
) -> PreflightReport:
    reasons = list(errors)
    for passed, reason in (
        (remote, "Remote/authentication not verified"),
        (base, "Target moved or base is not an ancestor"),
        (clean, "Integration tree is dirty or HEAD changed"),
        (gates, "Required final quality gates did not pass"),
        (not findings, "Secret scan requires remediation"),
        (not large, "Large/binary files require human review"),
    ):
        if not passed:
            reasons.append(reason)
    return PreflightReport(
        candidate_id=candidate.id,
        version=candidate.version,
        status="failed" if reasons else "passed",
        remote_reachable=remote,
        base_up_to_date=base,
        clean_integration_tree=clean,
        quality_gate_passed=gates,
        secret_scan_passed=not findings,
        secret_findings=findings,
        large_binary_findings=large,
        migration_lockfile_check={
            "status": "review_required" if special else "passed",
            "details": ", ".join(special),
        },
        risk_level="critical" if findings else "high" if reasons or special else "low",
        blocking_reasons=reasons,
    )

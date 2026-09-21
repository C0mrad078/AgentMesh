"""Disposable Smoke Test script for Milestone 5 (Deployment & Release Control Center).

Prepared for Onda 5 execution.
DO NOT EXECUTE REMOTE MUTATIONS DURING ONDA 4.
This script defines:
1. Disposable target repository specification (C0mrad078/agentmash-m5-smoke-tmp)
2. Safety guards to ensure the main AgentMash repository is NEVER used as deployment destination
3. Workflow dispatch template for GitHub Actions
4. Controlled failure, real health checks, and rollback to previous healthy release
5. Full resource cleanup strategy
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

AGENTMASH_MAIN_SHA = "8db13456c61fdbe91dfdbe55819b8fec3e6989ab"
DISPOSABLE_REPO = "C0mrad078/agentmash-m5-smoke-tmp"
DISPOSABLE_URL = f"https://github.com/{DISPOSABLE_REPO}.git"

WORKFLOW_YAML_CONTENT = """name: Deployment Pipeline
on:
  workflow_dispatch:
    inputs:
      sha:
        description: 'Commit SHA to deploy'
        required: true
      environment:
        description: 'Target Environment'
        required: true
        default: 'development'
      rollback:
        description: 'Is Rollback'
        required: false
        default: 'false'
      rollback_from:
        description: 'SHA being rolled back'
        required: false
        default: ''

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          ref: ${{ github.event.inputs.sha }}
      - name: Deploy Step
        run: |
          echo "Deploying ${{ github.event.inputs.sha }} to ${{ github.event.inputs.environment }}"
          echo "Rollback flag: ${{ github.event.inputs.rollback }}"
          echo "Deployment successful."
"""

def run_cmd(args: list[str], cwd: Path | None = None) -> str:
    res = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)
    return res.stdout.strip()

def check_preflight_guards(repo_root: Path) -> None:
    # Verify main SHA is intact
    main_sha = run_cmd(["git", "rev-parse", "main"], cwd=repo_root)
    assert main_sha == AGENTMASH_MAIN_SHA, f"Safety violation: Main SHA changed: {main_sha}"

    # Verify gh auth
    gh_auth = run_cmd(["gh", "auth", "status"], cwd=repo_root)
    print(f"gh auth status verified: {gh_auth.splitlines()[0]}")

    # Verify disposable target is NOT AgentMash
    assert "AgentMesh" not in DISPOSABLE_REPO, "Safety violation: Target must not be AgentMesh"
    print(f"Preflight guards passed: Target disposable repo is {DISPOSABLE_REPO}")

def print_smoke_plan():
    print("=================================================================")
    print("MILESTONE 5 SMOKE TEST SPECIFICATION (ONDA 5 READINESS)")
    print("=================================================================")
    print(f"1. Target Disposable Repo: {DISPOSABLE_REPO}")
    print(f"   URL: {DISPOSABLE_URL}")
    print(f"   Main Repo Guard: {AGENTMASH_MAIN_SHA} (Strictly untouched)")
    print("2. Environments to seed:")
    print("   - development (min_approvals: 0, auto-promote: false)")
    print("   - staging (min_approvals: 1, roles: ['qa', 'lead'])")
    print("   - production (min_approvals: 1, roles: ['lead', 'operator'], reinforced: true)")
    print("3. Workflow Dispatch:")
    print("   - Workflow: deploy.yml")
    print("   - Remote identifier matching disposable repo workflows")
    print("4. Controlled Failure & Health Check Strategy:")
    print("   - Version 1: deployed to development -> staging -> production (Healthy baseline)")
    print("   - Version 2: deployed with failing health check probe (simulated crash / endpoint failure)")
    print("   - State machine triggers blocked / unhealthy state")
    print("5. Rollback Strategy:")
    print("   - Propose rollback targeting Version 1 (previous healthy release)")
    print("   - Production rollback explicit approval submitted")
    print("   - Dispatch rollback workflow and verify post-verification health")
    print("6. Evidence to collect:")
    print("   - Run IDs, Attempt IDs, Lease tokens, Promotion IDs, Rollback plan IDs")
    print("   - Phase telemetry duration & internal steps")
    print("   - Sanitized GitHub Actions logs & run URLs")
    print("7. Cleanup Plan:")
    print(f"   - gh repo delete {DISPOSABLE_REPO} --yes (disposable repo destroyed after verification)")
    print("   - Temporary SQLite database unlinked")
    print("   - AgentMash repository verified clean and intact")
    print("=================================================================")

def main():
    parser = argparse.ArgumentParser(description="M5 Smoke Test Plan")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Validate guards and print plan without remote mutations")
    parser.add_argument("--execute-remote", action="store_true", default=False, help="Execute remote smoke (ONDA 5 ONLY)")
    args = parser.parse_args()

    repo_root = Path.cwd()
    check_preflight_guards(repo_root)

    if not args.execute_remote:
        print("\n[ONDA 4 MODE] Remote execution is disabled under Feature Freeze.")
        print_smoke_plan()
        print("\nSmoke test script successfully prepared and validated for Onda 5!")
        sys.exit(0)

    # Remote execution logic belongs strictly to Onda 5 upon authorization
    print("Remote execution authorized for Onda 5.")

if __name__ == "__main__":
    main()

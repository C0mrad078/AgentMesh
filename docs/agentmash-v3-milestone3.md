# AgentMash V3 Marco 3

This milestone adds the first operations surface for the persisted V3
parallel engine. Runtime bindings now expose enabled state, diagnostics and
reconciliation timestamps; the desktop has a RuntimeBindings control page and
the Agent form selects a binding from the live catalog instead of asking for
an opaque id.

Quality gates are represented as project profiles containing validated argv,
relative working directory, timeout/retry/log policy, source and approval
metadata. `core.integration.quality_gates` only proposes commands discovered
from project files and rejects shell interpreters or paths outside the
project. Execution remains a backend responsibility.

Migration `0017_integration_control_center.sql` adds profiles and the
auditable conflict, conflict-file, resolution-attempt, review and human
decision records. `IntegrationRepository` exposes these records to the
bridge and mission snapshots. A failed integration is persisted as a
classified conflict and shown in Agent Workspace; the integration branch and
the user's main branch remain separate.

The current assisted flow deliberately stops after recording the conflict so
that a future integrator session can be attached without silently choosing
ours or theirs. Binary, lockfile, migration/schema, generated and API
contract conflicts are classified conservatively and can be escalated to a
human. Marco 4 should complete the interactive integrator proposal/review
loop and add a real conflicting Codex smoke run.

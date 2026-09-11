# Frontend tests

Frontend unit/integration tests live **co-located with the code they test**,
under `desktop/src/**/__tests__/*.test.tsx`, following Vitest/Vite
convention (and so Vite's default module graph and path aliases resolve
without extra `root`/`include` configuration). Run them with:

```bash
cd desktop
npm run test
```

This directory is kept as the documented top-level location for any future
frontend **end-to-end** tests (e.g. a Playwright/WebDriver suite driving the
actual Tauri window), which are out of scope for Stage 1 — see the
"Limitações conhecidas" section of the root `README.md` for why the desktop
window's click-through flow is validated via `tests/smoke/` (against the real
sidecar process) instead of GUI automation in this stage.

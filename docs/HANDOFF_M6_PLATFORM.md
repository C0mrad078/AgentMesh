# Marco 6 — Platform & Packaging handoff

## RC packaging state

The Cargo and Tauri bundle manifests are set to `0.1.0-rc.1`. The new
`release-candidate.yml` workflow builds macOS Apple Silicon, macOS Intel, and
Windows x64 NSIS artifacts and uploads them as 14-day workflow artifacts. It
does not create tags or GitHub Releases. Until corporate signing credentials
are provisioned, outputs are classified **Unsigned Internal RC** and are not
for public distribution.

The Tauri build uses `frontendDist: "../dist"` and its production build command
compiles the frontend before packaging; the packaged frontend is static and
does not start Vite or a development server. The Python platform data layer
uses the user data directory for local application state, and CLI discovery
uses platform lookup/fallback behavior in the existing core.

## Important self-contained packaging limitation

This packaging-only wave is not yet a fully self-contained application. The
owned-file boundary excludes `desktop/src-tauri/src/bridge/process.rs`, whose
current production path still resolves Python from the checkout/venv and
embeds `CARGO_MANIFEST_DIR`. The RC verifier deliberately rejects absolute
checkout/runner paths; therefore packaging can fail that check until a later
authorized Rust change replaces the checkout launcher with a packaged,
target-specific core sidecar and removes the compile-time checkout path.
The app must not be described as independent of an installed Python/runtime
until that work and an end-to-end clean-machine smoke test pass.

The version scope here intentionally excludes `desktop/package.json`, the
Python package version, and `desktop/src-tauri/Cargo.lock`, as those paths were
not authorized for this wave. Cargo lockfile synchronization may consequently
be required by the integrating owner before release. Local `cargo check
--locked` confirms the lockfile must be updated; since Cargo.lock is outside
the authorized scope, local Rust check/clippy could not proceed with `--locked`.
The RC workflow resolves this package metadata in its ephemeral checkout; the
repository lockfile must be synchronized by an authorized owner for locked
local/CI validation.

## Updater preparation

Updater signing artifacts remain disabled. No private updater key was
generated, stored, or committed. Enabling Tauri updater distribution requires
the updater plugin to be registered in the Rust application, an endpoint and
matching public key in Tauri configuration, and these protected CI secrets:

- `TAURI_SIGNING_PRIVATE_KEY`
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` (if the key is encrypted)

Only the public key belongs in application configuration. Never put the
private key in source control, build artifacts, logs, or ordinary variables.

## Public distribution signing secrets

Before public distribution, provision protected environment secrets:

- macOS: `APPLE_CERTIFICATE` (base64 Developer ID Application certificate),
  `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`,
  `APPLE_PASSWORD` (app-specific password), and `APPLE_TEAM_ID` for signing
  and notarization.
- Windows: `WINDOWS_CERTIFICATE` (base64 code-signing certificate) and
  `WINDOWS_CERTIFICATE_PASSWORD`, plus the organization-approved signing
  service/timestamp configuration.
- Updater (separate from OS code signing): `TAURI_SIGNING_PRIVATE_KEY` and
  optionally `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`.

The workflow currently does not consume OS-signing secrets. It must be updated
to use the organization-approved signing/notarization process before the
classification can change from **Unsigned Internal RC**.

## Artifact verification

`scripts/verify_artifacts.py` reports SHA-256 and byte size, checks version and
architecture metadata where the package format exposes it, and rejects
secret-like content, development-only files, and absolute checkout/runner
paths. A passing packaging job is not a substitute for installation and
first-launch smoke tests on clean macOS and Windows machines.

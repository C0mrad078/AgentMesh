//! Resolves how to launch the Python sidecar for the current platform.
//!
//! This is the single place in the Rust codebase allowed to branch on
//! `cfg!(target_os = ...)` for the sidecar's own launch details -- every
//! other module treats "how do I start the core" as an opaque, already
//! platform-resolved `SidecarCommand`.
//!
//! ## Dev vs. production
//!
//! In development, the core runs from this repository's own Python virtual
//! environment (`<repo_root>/.venv`) via `python -m core.bridge.main`, with
//! `<repo_root>` located relative to this crate's manifest directory
//! (`desktop/src-tauri` -> up two levels). That is exactly right for
//! `tauri dev`, where the end user's machine is the developer's own.
//!
//! For a distributed build, the end user must never need Python installed
//! (see the project's portability rules). The intended production path is
//! to freeze `core/` with PyInstaller into a single binary and register it
//! as a Tauri `externalBin` sidecar, at which point this module's
//! production branch invokes that bundled binary directly instead of a
//! `python` interpreter. That freezing step is tracked as a Stage 2+
//! packaging task (see the root README's "Limitações conhecidas") --
//! Stage 1 ships the dev path fully working and documents the gap rather
//! than hiding it.
//!
//! `ORCH_PYTHON_BIN` and `ORCH_CORE_CWD` env vars override resolution for
//! CI/test environments where the repo layout or venv location differs.

use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
pub struct SidecarCommand {
    pub program: String,
    pub args: Vec<String>,
    pub cwd: PathBuf,
}

fn repo_root() -> PathBuf {
    // CARGO_MANIFEST_DIR is `<repo>/desktop/src-tauri` at compile time.
    let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    manifest_dir
        .parent()
        .and_then(Path::parent)
        .expect("desktop/src-tauri should have two parent directories")
        .to_path_buf()
}

fn venv_python(root: &Path) -> Option<PathBuf> {
    let candidate = if cfg!(target_os = "windows") {
        root.join(".venv").join("Scripts").join("python.exe")
    } else {
        root.join(".venv").join("bin").join("python")
    };
    candidate.exists().then_some(candidate)
}

pub fn resolve_sidecar_command() -> SidecarCommand {
    let root = std::env::var("ORCH_CORE_CWD")
        .map(PathBuf::from)
        .unwrap_or_else(|_| repo_root());

    let program = std::env::var("ORCH_PYTHON_BIN")
        .ok()
        .or_else(|| venv_python(&root).map(|p| p.to_string_lossy().into_owned()));

    let program = program.unwrap_or_else(|| {
        if cfg!(target_os = "windows") {
            "python".to_string()
        } else {
            "python3".to_string()
        }
    });

    SidecarCommand {
        program,
        args: vec!["-m".to_string(), "core.bridge.main".to_string()],
        cwd: root,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    // Environment variables are process-global state; serialize the tests
    // that touch them so they cannot interleave and observe each other's
    // overrides.
    static ENV_LOCK: Mutex<()> = Mutex::new(());

    #[test]
    fn explicit_python_bin_override_wins() {
        let _guard = ENV_LOCK.lock().unwrap();
        std::env::set_var("ORCH_PYTHON_BIN", "/custom/python");
        std::env::set_var("ORCH_CORE_CWD", "/some/repo");

        let cmd = resolve_sidecar_command();

        std::env::remove_var("ORCH_PYTHON_BIN");
        std::env::remove_var("ORCH_CORE_CWD");

        assert_eq!(cmd.program, "/custom/python");
        assert_eq!(cmd.cwd, PathBuf::from("/some/repo"));
        assert_eq!(cmd.args, vec!["-m", "core.bridge.main"]);
    }

    #[test]
    fn falls_back_to_a_bare_interpreter_name_without_a_venv() {
        let _guard = ENV_LOCK.lock().unwrap();
        std::env::remove_var("ORCH_PYTHON_BIN");
        std::env::set_var("ORCH_CORE_CWD", "/tmp/definitely-not-a-real-repo-root");

        let cmd = resolve_sidecar_command();

        std::env::remove_var("ORCH_CORE_CWD");

        let expected = if cfg!(target_os = "windows") {
            "python"
        } else {
            "python3"
        };
        assert_eq!(cmd.program, expected);
    }
}

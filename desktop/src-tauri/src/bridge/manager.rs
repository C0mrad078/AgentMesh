//! The bridge engine: owns the Python sidecar's lifecycle, the newline-JSON
//! protocol framing, and request/response correlation.
//!
//! One `BridgeManager` lives for the whole app session (see `AppState` in
//! `lib.rs`). A single long-lived supervisor task (`run_supervisor`) drives
//! the entire connect -> stream -> disconnect -> backoff -> reconnect cycle
//! as one plain loop; deliberately *not* as a set of async functions that
//! call each other recursively (connect -> stream -> handle-disconnect ->
//! reconnect -> connect -> ...), which is a real trap in async Rust: the
//! compiler has to inline each function's anonymous future type into the
//! next, and a genuine call cycle between them produces an infinitely-sized
//! (and therefore un-`Send`-able) future type. A single loop with plain,
//! non-recursive helper functions sidesteps that entirely.
//!
//! Responsibilities:
//!   * spawning the sidecar with a fresh per-session token (see
//!     `process::resolve_sidecar_command` for platform-specific launch
//!     details);
//!   * writing one JSON line per request to the child's stdin and matching
//!     each response back to its caller by `id` via a `oneshot` channel;
//!   * streaming `event` lines out as Tauri events for the frontend to
//!     subscribe to (execution progress, etc.);
//!   * detecting the sidecar dying (EOF on stdout) and driving reconnection
//!     with bounded exponential backoff, reporting connection status the
//!     whole time via `orchestrator://status` events so the UI's
//!     connected/initializing/reconnecting/offline indicator is always
//!     accurate.

use std::collections::{HashMap, VecDeque};
use std::process::Stdio;
use std::sync::Arc;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{AppHandle, Emitter};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};
use tokio::sync::{oneshot, Mutex, Notify};

use super::process::resolve_sidecar_command;
use super::protocol::{ErrorPayload, IncomingMessage, RequestMessage};

const REQUEST_TIMEOUT: Duration = Duration::from_secs(30);
/// After this many consecutive failed attempts, status is reported as
/// `Offline` rather than `Reconnecting` -- but the supervisor loop keeps
/// retrying in the background regardless, at a fixed slower cadence.
const FAST_RETRY_ATTEMPTS: u32 = 5;
const MAX_BACKOFF: Duration = Duration::from_secs(10);
/// "max 3 restarts within 5 minutes, then core unavailable" -- after this
/// many restart attempts inside `RESTART_WINDOW`, the supervisor stops
/// retrying on its own and waits for an explicit `reconnect_now()` call
/// instead of looping forever. A restart that stays up long enough to
/// reach `stream_until_disconnected` clears the window, so a sidecar that
/// merely restarts occasionally (not in a tight crash loop) is unaffected.
const MAX_RESTARTS_PER_WINDOW: usize = 3;
const RESTART_WINDOW: Duration = Duration::from_secs(300);
const STATUS_EVENT: &str = "orchestrator://status";
const MESSAGE_EVENT: &str = "orchestrator://event";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum BridgeStatus {
    Initializing,
    Connected,
    Reconnecting {
        attempt: u32,
    },
    Offline,
    /// The sidecar crash-looped `MAX_RESTARTS_PER_WINDOW` times within
    /// `RESTART_WINDOW`. Distinct from `Offline` (which still implies "the
    /// supervisor is quietly retrying in the background"): this state
    /// means automatic retries have stopped and the user must explicitly
    /// ask to try again (see `reconnect_now`).
    Unavailable,
    Error {
        message: String,
    },
}

fn backoff_for(attempt: u32) -> Duration {
    let millis = 500u64.saturating_mul(1u64 << attempt.min(4));
    Duration::from_millis(millis).min(MAX_BACKOFF)
}

struct Inner {
    child: Option<Child>,
    stdin: Option<ChildStdin>,
    pending: HashMap<String, oneshot::Sender<Result<Value, ErrorPayload>>>,
}

impl Inner {
    fn empty() -> Self {
        Self {
            child: None,
            stdin: None,
            pending: HashMap::new(),
        }
    }

    fn fail_all_pending(&mut self, message: &str) {
        for (_, tx) in self.pending.drain() {
            let _ = tx.send(Err(ErrorPayload {
                code: "BRIDGE_DISCONNECTED".to_string(),
                message: message.to_string(),
                details: Value::Null,
            }));
        }
    }
}

pub struct BridgeManager {
    app: AppHandle,
    session_token: String,
    inner: Mutex<Inner>,
    status: Mutex<BridgeStatus>,
    reconnect_notify: Notify,
    restart_history: Mutex<VecDeque<Instant>>,
}

impl BridgeManager {
    pub fn new(app: AppHandle) -> Arc<Self> {
        Arc::new(Self {
            app,
            session_token: uuid::Uuid::new_v4().to_string(),
            inner: Mutex::new(Inner::empty()),
            status: Mutex::new(BridgeStatus::Initializing),
            reconnect_notify: Notify::new(),
            restart_history: Mutex::new(VecDeque::new()),
        })
    }

    pub async fn status(&self) -> BridgeStatus {
        self.status.lock().await.clone()
    }

    async fn set_status(&self, status: BridgeStatus) {
        log::info!("bridge status -> {status:?}");
        *self.status.lock().await = status.clone();
        let _ = self.app.emit(STATUS_EVENT, &status);
    }

    /// Runs for the lifetime of the application. Never returns.
    pub async fn run_supervisor(self: Arc<Self>) {
        let mut attempt: u32 = 0;

        loop {
            match self.connect_once().await {
                Ok(stdout) => {
                    attempt = 0;
                    self.restart_history.lock().await.clear();
                    self.stream_until_disconnected(stdout).await;
                }
                Err(e) => {
                    log::error!("failed to start Orquestrador core: {e}");
                }
            }

            attempt += 1;

            if self.record_restart_and_check_crash_loop().await {
                self.set_status(BridgeStatus::Unavailable).await;
                self.reconnect_notify.notified().await;
                self.restart_history.lock().await.clear();
                attempt = 0;
                continue;
            }

            let status = if attempt <= FAST_RETRY_ATTEMPTS {
                BridgeStatus::Reconnecting { attempt }
            } else {
                BridgeStatus::Offline
            };
            self.set_status(status).await;

            tokio::select! {
                _ = tokio::time::sleep(backoff_for(attempt)) => {}
                _ = self.reconnect_notify.notified() => {
                    attempt = 0;
                }
            }
        }
    }

    /// Records one restart attempt and reports whether the sidecar has now
    /// crash-looped `MAX_RESTARTS_PER_WINDOW` times within `RESTART_WINDOW`.
    async fn record_restart_and_check_crash_loop(&self) -> bool {
        let mut history = self.restart_history.lock().await;
        let now = Instant::now();
        while let Some(&front) = history.front() {
            if now.duration_since(front) > RESTART_WINDOW {
                history.pop_front();
            } else {
                break;
            }
        }
        history.push_back(now);
        history.len() > MAX_RESTARTS_PER_WINDOW
    }

    /// User-triggered retry (e.g. an "offline" banner's button). A no-op if
    /// already connected; otherwise wakes the supervisor loop immediately
    /// instead of waiting out its current backoff delay.
    pub async fn reconnect_now(&self) -> Result<(), String> {
        if self.status().await == BridgeStatus::Connected {
            return Ok(());
        }
        self.set_status(BridgeStatus::Initializing).await;
        self.reconnect_notify.notify_one();
        Ok(())
    }

    async fn connect_once(self: &Arc<Self>) -> Result<ChildStdout, String> {
        let cmd = resolve_sidecar_command();
        log::info!(
            "starting sidecar: {} {:?} (cwd={:?})",
            cmd.program,
            cmd.args,
            cmd.cwd
        );

        let mut child = Command::new(&cmd.program)
            .args(&cmd.args)
            .current_dir(&cmd.cwd)
            .env("ORCH_SESSION_TOKEN", &self.session_token)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .map_err(|e| format!("Failed to start Python sidecar ({}): {e}", cmd.program))?;

        let stdin = child.stdin.take().expect("piped stdin");
        let stdout = child.stdout.take().expect("piped stdout");
        let stderr = child.stderr.take().expect("piped stderr");

        {
            let mut inner = self.inner.lock().await;
            inner.child = Some(child);
            inner.stdin = Some(stdin);
        }

        // Forward the sidecar's own structured logs (stderr) into Rust's
        // log sink instead of discarding them; they never touch stdout,
        // which is reserved for the protocol.
        tokio::spawn(async move {
            let mut lines = BufReader::new(stderr).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                log::debug!(target: "orchestrator-core", "{line}");
            }
        });

        Ok(stdout)
    }

    /// Reads protocol lines until the sidecar's stdout closes (process
    /// exited or the pipe broke), then cleans up shared state. Does not
    /// decide anything about reconnection -- that is `run_supervisor`'s job.
    async fn stream_until_disconnected(self: &Arc<Self>, stdout: ChildStdout) {
        let mut lines = BufReader::new(stdout).lines();

        loop {
            match lines.next_line().await {
                Ok(Some(line)) => {
                    if line.trim().is_empty() {
                        continue;
                    }
                    self.handle_incoming_line(&line).await;
                }
                Ok(None) => {
                    log::warn!("sidecar stdout closed (EOF)");
                    break;
                }
                Err(e) => {
                    log::error!("error reading sidecar stdout: {e}");
                    break;
                }
            }
        }

        let mut inner = self.inner.lock().await;
        inner.child = None;
        inner.stdin = None;
        inner.fail_all_pending("The connection to the Orquestrador core was lost.");
    }

    async fn handle_incoming_line(&self, line: &str) {
        let parsed: Result<IncomingMessage, _> = serde_json::from_str(line);
        match parsed {
            Ok(IncomingMessage::Hello(hello)) => {
                if hello.session != self.session_token {
                    log::error!("sidecar hello carried an unexpected session token");
                    self.set_status(BridgeStatus::Error {
                        message: "Sidecar identity could not be verified.".to_string(),
                    })
                    .await;
                    return;
                }
                self.set_status(BridgeStatus::Connected).await;
            }
            Ok(IncomingMessage::Response(response)) => {
                let mut inner = self.inner.lock().await;
                if let Some(tx) = inner.pending.remove(&response.id) {
                    let result = if response.ok {
                        Ok(response.result)
                    } else {
                        Err(response.error.unwrap_or(ErrorPayload {
                            code: "UNKNOWN".to_string(),
                            message: "Request failed without error details.".to_string(),
                            details: Value::Null,
                        }))
                    };
                    let _ = tx.send(result);
                }
            }
            Ok(IncomingMessage::Event(event)) => {
                let _ = self.app.emit(
                    MESSAGE_EVENT,
                    serde_json::json!({ "event": event.event, "payload": event.payload }),
                );
            }
            Ok(IncomingMessage::Unknown) => {
                log::warn!("received unrecognized bridge message: {line}");
            }
            Err(e) => {
                log::error!("failed to parse bridge line as JSON: {e} (line={line})");
            }
        }
    }

    pub async fn invoke(
        self: &Arc<Self>,
        command: String,
        params: Value,
    ) -> Result<Value, ErrorPayload> {
        if self.status().await != BridgeStatus::Connected {
            return Err(ErrorPayload {
                code: "BRIDGE_UNAVAILABLE".to_string(),
                message: "The Orquestrador core is not connected.".to_string(),
                details: Value::Null,
            });
        }

        let id = uuid::Uuid::new_v4().to_string();
        let request = RequestMessage::new(id.clone(), self.session_token.clone(), command, params);
        let line = match serde_json::to_string(&request) {
            Ok(s) => s,
            Err(e) => {
                return Err(ErrorPayload {
                    code: "SERIALIZATION_ERROR".to_string(),
                    message: format!("Failed to serialize request: {e}"),
                    details: Value::Null,
                })
            }
        };

        let (tx, rx) = oneshot::channel();
        {
            let mut inner = self.inner.lock().await;
            let Some(stdin) = inner.stdin.as_mut() else {
                return Err(ErrorPayload {
                    code: "BRIDGE_UNAVAILABLE".to_string(),
                    message: "The Orquestrador core is not connected.".to_string(),
                    details: Value::Null,
                });
            };
            if let Err(e) = stdin.write_all(format!("{line}\n").as_bytes()).await {
                return Err(ErrorPayload {
                    code: "BRIDGE_WRITE_FAILED".to_string(),
                    message: format!("Failed to write request to sidecar: {e}"),
                    details: Value::Null,
                });
            }
            if let Err(e) = stdin.flush().await {
                return Err(ErrorPayload {
                    code: "BRIDGE_WRITE_FAILED".to_string(),
                    message: format!("Failed to flush request to sidecar: {e}"),
                    details: Value::Null,
                });
            }
            inner.pending.insert(id.clone(), tx);
        }

        match tokio::time::timeout(REQUEST_TIMEOUT, rx).await {
            Ok(Ok(result)) => result,
            Ok(Err(_)) => Err(ErrorPayload {
                code: "BRIDGE_DISCONNECTED".to_string(),
                message: "Connection to the core was lost while waiting for a response."
                    .to_string(),
                details: Value::Null,
            }),
            Err(_) => {
                self.inner.lock().await.pending.remove(&id);
                Err(ErrorPayload {
                    code: "TIMEOUT".to_string(),
                    message: format!("Request timed out after {}s.", REQUEST_TIMEOUT.as_secs()),
                    details: Value::Null,
                })
            }
        }
    }
}

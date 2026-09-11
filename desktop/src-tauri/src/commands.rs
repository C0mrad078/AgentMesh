//! Tauri commands: the entire surface the frontend can call into Rust with.
//!
//! Deliberately tiny and generic (`bridge_invoke` + `bridge_status` +
//! `bridge_reconnect`) rather than one Tauri command per orchestrator
//! operation -- the allowlist of *what* can actually be done lives once, in
//! Python (`core.security.allowlist.BridgeCommand`), so it never has to be
//! kept in sync with a second, parallel list of Tauri command names here.

use std::sync::Arc;

use serde_json::Value;
use tauri::State;

use crate::bridge::protocol::ErrorPayload;
use crate::bridge::{BridgeManager, BridgeStatus};

#[tauri::command]
pub async fn bridge_invoke(
    manager: State<'_, Arc<BridgeManager>>,
    command: String,
    params: Option<Value>,
) -> Result<Value, ErrorPayload> {
    manager
        .invoke(command, params.unwrap_or(Value::Object(Default::default())))
        .await
}

#[tauri::command]
pub async fn bridge_status(manager: State<'_, Arc<BridgeManager>>) -> Result<BridgeStatus, String> {
    Ok(manager.status().await)
}

#[tauri::command]
pub async fn bridge_reconnect(manager: State<'_, Arc<BridgeManager>>) -> Result<(), String> {
    manager.reconnect_now().await
}

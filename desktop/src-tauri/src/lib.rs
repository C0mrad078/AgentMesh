mod bridge;
mod commands;

use bridge::BridgeManager;
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(
            tauri_plugin_log::Builder::new()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .invoke_handler(tauri::generate_handler![
            commands::bridge_invoke,
            commands::bridge_status,
            commands::bridge_reconnect,
        ])
        .setup(|app| {
            let manager = BridgeManager::new(app.handle().clone());
            app.manage(manager.clone());

            tauri::async_runtime::spawn(async move {
                manager.run_supervisor().await;
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

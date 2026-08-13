mod commands;
mod tray;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![
            commands::health::check_server_reachable,
            commands::files::pick_document,
            commands::splash::close_splash,
            commands::neko_agent::neko_detect_agents,
            commands::neko_agent::neko_agent_profiles,
            commands::neko_agent::neko_spawn_agent,
            commands::neko_agent::neko_write_stdin,
            commands::neko_agent::neko_kill_agent,
            commands::neko_agent::neko_kill_all_agents,
        ])
        .setup(|app| {
            // Create system tray
            tray::create_tray(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            // Minimize to tray on close (main window only)
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while running Wiii desktop")
        .run(|_app, event| {
            // Fail-closed: no agent process outlives the app (FR-009, #886).
            if let tauri::RunEvent::Exit = event {
                commands::neko_agent::kill_all();
            }
        });
}

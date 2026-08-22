mod commands;
mod neko;
mod tray;

use neko::runtime::NekoRuntime;
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // Reject a second journal owner before setup. Bring the existing
        // Workbench to the foreground instead of surfacing a generic lease
        // error from a second process.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![
            commands::health::check_server_reachable,
            commands::files::pick_document,
            commands::files::neko_list_workspace_files,
            commands::files::neko_read_workspace_file,
            commands::files::neko_workspace_changes,
            commands::files::neko_workspace_diff,
            commands::splash::close_splash,
            commands::neko_agent::neko_control_provider_list,
            commands::neko_agent::neko_control_provider_profiles,
            commands::neko_agent::neko_control_session_list,
            commands::neko_agent::neko_control_session_start,
            commands::neko_agent::neko_control_session_write,
            commands::neko_agent::neko_control_session_cancel,
            commands::neko_agent::neko_control_events_read,
        ])
        .setup(|app| {
            let data_dir = app.path().app_local_data_dir()?;
            let runtime = NekoRuntime::open(&data_dir.join("neko-runtime-v1.sqlite3"))
                .map_err(std::io::Error::other)?;
            app.manage(runtime);
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
        .run(|app, event| {
            // Phase 2A is in-process: a graceful app exit cancels every owned
            // child. Hard-crash recovery is classified from the journal.
            if let tauri::RunEvent::Exit = event {
                app.state::<NekoRuntime>().kill_all(app);
            }
        });
}

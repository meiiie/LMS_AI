fn main() {
    const COMMANDS: &[&str] = &[
        "check_server_reachable",
        "pick_document",
        "neko_list_workspace_files",
        "neko_read_workspace_file",
        "neko_workspace_changes",
        "neko_workspace_diff",
        "close_splash",
        "neko_control_provider_list",
        "neko_control_provider_profiles",
        "neko_control_session_list",
        "neko_control_session_start",
        "neko_control_session_write",
        "neko_control_session_cancel",
        "neko_control_events_read",
    ];

    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(COMMANDS)),
    )
    .expect("failed to build Wiii desktop metadata")
}

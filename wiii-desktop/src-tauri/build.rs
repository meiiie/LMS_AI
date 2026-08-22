fn main() {
    const COMMANDS: &[&str] = &[
        "check_server_reachable",
        "pick_document",
        "neko_list_workspace_files",
        "neko_read_workspace_file",
        "neko_workspace_changes",
        "neko_workspace_diff",
        "close_splash",
        "neko_detect_agents",
        "neko_agent_profiles",
        "neko_spawn_agent",
        "neko_write_stdin",
        "neko_kill_agent",
        "neko_kill_all_agents",
    ];

    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(COMMANDS)),
    )
    .expect("failed to build Wiii desktop metadata")
}

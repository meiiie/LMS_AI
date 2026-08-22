use serde_json::Value;
use std::{fs, path::PathBuf};

fn tauri_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn read_json(relative: &str) -> Value {
    let path = tauri_root().join(relative);
    let text = fs::read_to_string(&path)
        .unwrap_or_else(|error| panic!("failed to read {}: {error}", path.display()));
    serde_json::from_str(&text)
        .unwrap_or_else(|error| panic!("failed to parse {}: {error}", path.display()))
}

#[test]
fn csp_is_enabled_with_required_fail_closed_directives() {
    let config = read_json("tauri.conf.json");
    let csp = config["app"]["security"]["csp"]
        .as_object()
        .expect("desktop CSP must be a directive map");

    assert_eq!(csp["object-src"], "'none'");
    assert_eq!(csp["base-uri"], "'self'");
    assert_eq!(csp["form-action"], "'self'");
    assert!(!csp["script-src"]
        .as_str()
        .unwrap_or_default()
        .contains("'unsafe-eval'"));
}

#[test]
fn splash_has_only_its_startup_command() {
    let splash = read_json("capabilities/splash.json");
    assert_eq!(splash["windows"], serde_json::json!(["splashscreen"]));
    assert_eq!(
        splash["permissions"],
        serde_json::json!(["allow-close-splash"])
    );
}

#[test]
fn every_workbench_capability_excludes_the_splash_window() {
    for name in [
        "workbench-base",
        "workbench-files",
        "workbench-network",
        "workbench-agents",
        "workbench-notifications",
    ] {
        let capability = read_json(&format!("capabilities/{name}.json"));
        assert_eq!(capability["windows"], serde_json::json!(["main"]), "{name}");
    }
}

#[test]
fn native_http_scope_has_no_global_remote_wildcard() {
    let network = read_json("capabilities/workbench-network.json");
    let rendered = serde_json::to_string(&network).expect("network capability is serializable");
    assert!(!rendered.contains("https://**"));
    assert!(rendered.contains("https://wiii.holilihu.online/**"));
}

#[test]
fn tauri_config_enables_only_the_reviewed_capability_set() {
    let config = read_json("tauri.conf.json");
    assert_eq!(
        config["app"]["security"]["capabilities"],
        serde_json::json!([
            "splash",
            "workbench-base",
            "workbench-files",
            "workbench-network",
            "workbench-agents",
            "workbench-notifications"
        ])
    );
}

#[test]
fn main_webview_has_no_raw_agent_process_primitive() {
    let agents = read_json("capabilities/workbench-agents.json");
    let windows = agents["windows"]
        .as_array()
        .expect("agent capability declares windows");
    assert_eq!(windows, serde_json::json!(["main"]).as_array().unwrap());
    let permissions = agents["permissions"]
        .as_array()
        .expect("agent capability declares permissions")
        .iter()
        .map(|entry| {
            entry
                .as_str()
                .or_else(|| entry.get("identifier").and_then(serde_json::Value::as_str))
                .expect("permission is a string or scoped identifier")
        })
        .collect::<Vec<_>>();

    for forbidden in [
        "allow-neko-spawn-agent",
        "allow-neko-write-stdin",
        "allow-neko-kill-agent",
        "allow-neko-kill-all-agents",
    ] {
        assert!(
            !permissions.contains(&forbidden),
            "raw primitive remains: {forbidden}"
        );
    }
    for required in [
        "allow-neko-control-provider-list",
        "allow-neko-control-provider-profiles",
        "allow-neko-control-session-list",
        "allow-neko-control-session-start",
        "allow-neko-control-session-write",
        "allow-neko-control-session-cancel",
        "allow-neko-control-events-read",
    ] {
        assert!(
            permissions.contains(&required),
            "missing scoped command: {required}"
        );
    }
}

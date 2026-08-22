use tauri::Manager;

fn is_splash_window(label: &str) -> bool {
    label == "splashscreen"
}

/// Close the splash screen and show the main application window.
/// Called from splashscreen.html after startup sequence completes.
#[tauri::command]
pub fn close_splash(window: tauri::Window) -> Result<(), String> {
    if !is_splash_window(window.label()) {
        return Err("close_splash is only available to the splashscreen window".into());
    }

    // Close splash screen
    if let Some(splash) = window.get_webview_window("splashscreen") {
        let _ = splash.close();
    }

    // Show and focus main window
    if let Some(main) = window.get_webview_window("main") {
        let _ = main.set_skip_taskbar(false);
        let _ = main.show();
        let _ = main.set_focus();
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::is_splash_window;

    #[test]
    fn close_splash_authority_is_label_bound() {
        assert!(is_splash_window("splashscreen"));
        assert!(!is_splash_window("main"));
        assert!(!is_splash_window("splashscreen-preview"));
    }
}

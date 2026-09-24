mod cli;
mod commands;
mod downloads;
mod navigation;
mod parity;
mod platform;
mod runtime;
mod state;
mod updates;
mod windows;
mod zoom;

pub(crate) use runtime::{BridgeError, BridgeResult, CONTAINER_NAME};

pub fn run() {
    use tauri::Manager;

    let host = runtime::HostState::default();
    let window_port = host.hosted_port.clone();
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            windows::focus_active(app);
        }))
        .manage(host)
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(commands::handler!())
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::CloseRequested { .. }) {
                // Both webviews are created up front and one is always hidden. Exiting
                // here prevents that hidden companion from leaving a headless process.
                window.app_handle().exit(0);
            }
        })
        .setup(move |app| {
            windows::create_desktop_windows(app, window_port.clone())?;
            runtime::start_packaged_smoke(app.handle().clone());
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running omnideck");
}

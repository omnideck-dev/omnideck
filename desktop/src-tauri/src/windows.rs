use crate::{
    downloads,
    navigation::{hosted_navigation, is_hosted_app_url, is_local_setup_url, HostedNavigation},
    platform,
    runtime::{BridgeError, BridgeResult, HostState},
    updates, zoom,
};
use std::sync::{Arc, RwLock};
use tauri::{
    webview::{Color, NewWindowResponse},
    AppHandle, Manager, WebviewUrl, WebviewWindowBuilder,
};

const HOSTED_BRIDGE_SCRIPT: &str = r#"
(() => {
  const updateListeners = new Set();
  const invoke = (command, args = {}) => {
    const core = window.__TAURI__?.core;
    if (!core?.invoke) return Promise.reject(new Error('The desktop host bridge is unavailable.'));
    return core.invoke(command, args);
  };

  window.omnideckHost = Object.freeze({
    currentUpdate: () => invoke('current_update'),
    checkForUpdate: () => invoke('check_for_update'),
    installUpdate: () => invoke('install_update'),
    deferUpdate: () => invoke('defer_update'),
    skipUpdate: () => invoke('skip_update'),
    onUpdate(listener) {
      updateListeners.add(listener);
      return () => updateListeners.delete(listener);
    },
  });

  window.addEventListener('omnideck:update', (event) => {
    updateListeners.forEach((listener) => listener(event.detail ?? null));
  });

  window.addEventListener('keydown', (event) => {
    if (event.altKey) return;
    const key = String(event.key || '').toLowerCase();
    const accelerator = event.ctrlKey || event.metaKey;
    const refresh = (key === 'f5' && !accelerator) || (accelerator && key === 'r');
    if (!refresh) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    window.location.reload();
  }, { capture: true });
})();
"#;

pub(crate) fn focus_active(app: &AppHandle) {
    let active = app
        .get_webview_window("hosted-app")
        .filter(|window| window.is_visible().unwrap_or(false))
        .or_else(|| app.get_webview_window("main"));
    if let Some(window) = active {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

pub(crate) fn show_hosted(app: &AppHandle, host: &HostState, port: u16) -> BridgeResult<()> {
    *host.hosted_port.write().map_err(|_| {
        BridgeError::new("STATE_LOCK_FAILED", "The hosted origin lock was poisoned.")
    })? = Some(port);
    let hosted = app.get_webview_window("hosted-app").ok_or_else(|| {
        BridgeError::new(
            "WINDOW_MISSING",
            "The hosted application window is unavailable.",
        )
    })?;
    let url = tauri::Url::parse(&format!("http://127.0.0.1:{port}"))
        .map_err(|error| BridgeError::new("INVALID_APP_URL", error.to_string()))?;
    hosted
        .navigate(url)
        .map_err(|error| BridgeError::new("WINDOW_UPDATE_FAILED", error.to_string()))?;
    hosted
        .show()
        .map_err(|error| BridgeError::new("WINDOW_UPDATE_FAILED", error.to_string()))?;
    hosted
        .set_focus()
        .map_err(|error| BridgeError::new("WINDOW_UPDATE_FAILED", error.to_string()))?;
    if let Some(main) = app.get_webview_window("main") {
        main.hide()
            .map_err(|error| BridgeError::new("WINDOW_UPDATE_FAILED", error.to_string()))?;
    }
    updates::schedule_update_checks(app, host);
    Ok(())
}

pub(crate) fn show_setup(app: &AppHandle) -> BridgeResult<()> {
    if let Some(hosted) = app.get_webview_window("hosted-app") {
        hosted
            .hide()
            .map_err(|error| BridgeError::new("WINDOW_UPDATE_FAILED", error.to_string()))?;
    }
    let main = app
        .get_webview_window("main")
        .ok_or_else(|| BridgeError::new("WINDOW_MISSING", "The setup window is unavailable."))?;
    main.show()
        .map_err(|error| BridgeError::new("WINDOW_UPDATE_FAILED", error.to_string()))?;
    main.set_focus()
        .map_err(|error| BridgeError::new("WINDOW_UPDATE_FAILED", error.to_string()))
}

pub(crate) fn create_desktop_windows(
    app: &tauri::App,
    hosted_port: Arc<RwLock<Option<u16>>>,
) -> tauri::Result<()> {
    zoom::with_native_hotkeys(
        WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
            .title("omnideck")
            .background_color(Color(12, 14, 20, 255))
            .inner_size(1280.0, 820.0)
            .min_inner_size(880.0, 620.0),
    )
    .on_navigation(is_local_setup_url)
    .on_new_window(|_, _| NewWindowResponse::Deny)
    .build()?;

    let navigation_port = hosted_port.clone();
    let new_window_port = hosted_port;
    let app_handle = app.handle().clone();
    zoom::with_native_hotkeys(
        WebviewWindowBuilder::new(
            app,
            "hosted-app",
            WebviewUrl::App("hosted-placeholder.html".into()),
        )
        .title("omnideck")
        .visible(false)
        .inner_size(1440.0, 900.0)
        .min_inner_size(960.0, 640.0)
        .background_color(Color(12, 14, 20, 255))
        .enable_clipboard_access(),
    )
    .initialization_script(HOSTED_BRIDGE_SCRIPT)
    .on_download(downloads::handle)
    .on_navigation(move |url| {
        match hosted_navigation(url, navigation_port.read().ok().and_then(|port| *port)) {
            HostedNavigation::Allow => true,
            HostedNavigation::OpenExternal => {
                let _ = platform::open_url(url.as_str());
                false
            }
            HostedNavigation::Deny => false,
        }
    })
    .on_new_window(move |url, _| {
        let expected_port = new_window_port.read().ok().and_then(|port| *port);
        match hosted_navigation(&url, expected_port) {
            HostedNavigation::Allow => {
                if is_hosted_app_url(&url, expected_port) {
                    if let Some(window) = app_handle.get_webview_window("hosted-app") {
                        let _ = window.navigate(url);
                    }
                }
            }
            HostedNavigation::OpenExternal => {
                let _ = platform::open_url(url.as_str());
            }
            HostedNavigation::Deny => {}
        }
        NewWindowResponse::Deny
    })
    .build()?;
    Ok(())
}

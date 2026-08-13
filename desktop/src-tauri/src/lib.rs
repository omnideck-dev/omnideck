mod cli;
mod parity;
mod platform;
mod state;
mod updates;

use cli::{
    instance_status, parse_instance_status, require_success, run_cli, run_fixed, runtime_status,
    validate_bundled_cli, FixedOperation, RuntimeStatus, EXPECTED_CLI_COMMIT, EXPECTED_CLI_VERSION,
    SETUP_TIMEOUT,
};
use parity::SetupState;
use serde::Serialize;
use state::{
    image_manifest, persisted_port, read_setup_record, reserve_and_persist_port, save_setup_record,
    ImageManifest, APP_VERSION,
};
use std::{
    collections::HashSet,
    fmt, fs,
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc, RwLock,
    },
    time::Duration,
};
use tauri::{
    ipc::Channel,
    webview::{Color, DownloadEvent, NewWindowResponse},
    AppHandle, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder,
};
use tauri_plugin_notification::NotificationExt;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

const CONTAINER_NAME: &str = "omnideck-desktop";
const HOME_VOLUME: &str = "omnideck-desktop-home";
const STATE_VOLUME: &str = "omnideck-desktop-state";
const DOWNLOAD_URL: &str = "https://github.com/omnideck-dev/omnideck/releases";
const SUPPORTED_SYSTEMS_URL: &str = "https://github.com/omnideck-dev/omnideck#prerequisites";
const HEALTH_TIMEOUT: Duration = Duration::from_secs(120);
const UPDATE_FIRST_CHECK: Duration = Duration::from_secs(10);
const UPDATE_INTERVAL: Duration = Duration::from_secs(6 * 60 * 60);
const ZOOM_CONTROL_SCRIPT: &str = r#"
(() => {
  if (window.__omnideckZoomControlsInstalled) return;
  window.__omnideckZoomControlsInstalled = true;

  const minZoom = 0.2;
  const maxZoom = 10;
  const zoomStep = 0.2;
  let zoomLevel = 1;

  const setZoom = (next) => {
    zoomLevel = Math.min(Math.max(next, minZoom), maxZoom);
    window.__omnideckRequestedZoom = zoomLevel;
    document.documentElement.style.zoom = String(zoomLevel);
    window.__omnideckDesktopZoom = zoomLevel;
    window.dispatchEvent(new CustomEvent('omnideck:zoom-changed', {
      detail: zoomLevel,
    }));
  };

  window.addEventListener('keydown', (event) => {
    window.__omnideckLastZoomInput = {
      type: 'keydown', key: event.key, ctrlKey: event.ctrlKey, metaKey: event.metaKey,
    };
    if (event.altKey) return;
    const accelerator = event.ctrlKey || event.metaKey;
    const key = String(event.key || '').toLowerCase();
    if (!accelerator || !['+', '=', 'add', '-', '_', 'subtract', '0'].includes(key)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (key === '0') setZoom(1);
    else if (['+', '=', 'add'].includes(key)) setZoom(zoomLevel + zoomStep);
    else setZoom(zoomLevel - zoomStep);
  }, { capture: true });

  window.addEventListener('wheel', (event) => {
    window.__omnideckLastZoomInput = {
      type: 'wheel', deltaY: event.deltaY, ctrlKey: event.ctrlKey, metaKey: event.metaKey,
    };
    if ((!event.ctrlKey && !event.metaKey) || event.deltaY === 0) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    setZoom(zoomLevel + (event.deltaY < 0 ? zoomStep : -zoomStep));
  }, { capture: true, passive: false });
})();
"#;
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

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct BridgeError {
    code: String,
    message: String,
    stderr: Option<String>,
    stage: Option<String>,
}

impl BridgeError {
    fn new(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
            stderr: None,
            stage: None,
        }
    }

    fn with_stderr(mut self, stderr: String) -> Self {
        if !stderr.trim().is_empty() {
            self.stderr = Some(stderr);
        }
        self
    }

    fn technical(&self) -> String {
        match &self.stderr {
            Some(stderr) => format!("{}\n{}", self.message, stderr),
            None => self.message.clone(),
        }
    }
}

impl fmt::Display for BridgeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for BridgeError {}
type BridgeResult<T> = Result<T, BridgeError>;

#[derive(Debug, Serialize)]
struct BootstrapResult {
    action: &'static str,
    reason: String,
}

#[derive(Clone)]
struct HostState {
    hosted_port: Arc<RwLock<Option<u16>>>,
    setup_reason: Arc<RwLock<String>>,
    setup_running: Arc<AtomicBool>,
    app_ready: Arc<AtomicBool>,
    offered_actions: Arc<RwLock<HashSet<String>>>,
    available_update: Arc<RwLock<Option<updates::UpdateTarget>>>,
    deferred_version: Arc<RwLock<Option<String>>>,
    update_target: Arc<RwLock<Option<updates::UpdateTarget>>>,
    update_checks_started: Arc<AtomicBool>,
}

impl Default for HostState {
    fn default() -> Self {
        let update_state = updates::read_state();
        let setup_record = read_setup_record();
        let available_update = setup_record
            .as_ref()
            .and_then(|record| updates::known_update(&record.image_version));
        // An update writes its selected immutable image into setup-state before
        // reconciling the environment. Rehydrate that selection after a crash
        // so Resume cannot accidentally fall back to the packaged older image.
        let update_target = setup_record.as_ref().and_then(|record| {
            interrupted_update_target(
                &record.status,
                &record.reason,
                &record.image_version,
                &record.image_ref,
            )
        });
        Self {
            hosted_port: Arc::new(RwLock::new(None)),
            setup_reason: Arc::new(RwLock::new("first-run".into())),
            setup_running: Arc::new(AtomicBool::new(false)),
            app_ready: Arc::new(AtomicBool::new(false)),
            offered_actions: Arc::new(RwLock::new(HashSet::new())),
            available_update: Arc::new(RwLock::new(available_update)),
            deferred_version: Arc::new(RwLock::new(update_state.deferred_version)),
            update_target: Arc::new(RwLock::new(update_target)),
            update_checks_started: Arc::new(AtomicBool::new(false)),
        }
    }
}

fn interrupted_update_target(
    status: &str,
    reason: &str,
    version: &str,
    image_ref: &str,
) -> Option<updates::UpdateTarget> {
    (status == "in-progress" && reason == "update").then(|| updates::UpdateTarget {
        version: version.to_owned(),
        image_ref: image_ref.to_owned(),
    })
}

fn setup_state_from_cli_event(
    reason: &str,
    event: &serde_json::Value,
    last_step: &mut Option<String>,
) -> Option<SetupState> {
    let stage = event.get("stage").and_then(|value| value.as_str())?;
    let state = event
        .get("state")
        .and_then(|value| value.as_str())
        .unwrap_or("");
    let event_step = event
        .get("substage")
        .and_then(|value| value.as_str())
        .filter(|value| parity::step_index(value).is_some())
        .map(str::to_owned);
    let step = event_step
        .or_else(|| last_step.clone())
        .or_else(|| match stage {
            "environment" => Some("secure-space".to_owned()),
            "download" | "pull_image" => Some("app-download".to_owned()),
            "startup" => Some("startup".to_owned()),
            _ => Some(parity::first_step().to_owned()),
        });
    if let Some(step) = &step {
        *last_step = Some(step.clone());
    }
    let progress = event.get("progress").and_then(|value| value.as_f64());
    let activity = event
        .get("activity")
        .and_then(|value| value.as_str())
        .map(str::to_owned)
        .filter(|value| !value.is_empty());
    let event_detail = event
        .get("detail")
        .and_then(|value| value.as_str())
        .map(str::to_owned)
        .filter(|value| !value.is_empty());
    let status = event
        .get("status")
        .and_then(|value| value.as_str())
        .or(event_detail.as_deref())
        .map(str::to_owned)
        .filter(|value| !value.is_empty());
    let activity = if status.as_deref() == Some("Switching Podman machines") {
        event_detail.or(activity)
    } else {
        activity
    };
    let progress = if state == "done" { Some(1.0) } else { progress };
    Some(parity::working_step(
        reason,
        step.as_deref(),
        progress,
        activity,
        status,
    ))
}

#[derive(Clone, Copy)]
enum SetupEventSource {
    Runtime,
    Environment,
}

fn setup_event_phase(source: SetupEventSource, stage: &str) -> Option<usize> {
    match source {
        SetupEventSource::Runtime => parity::phase_index(stage),
        SetupEventSource::Environment if stage == "pull_image" => parity::phase_index("download"),
        SetupEventSource::Environment => parity::phase_index("startup"),
    }
}

fn forward_setup_event(
    line: &str,
    reason: &str,
    last_step: &mut Option<String>,
    reached_phase: &AtomicUsize,
    channel: &Channel<SetupState>,
    source: SetupEventSource,
) {
    let Ok(event) = serde_json::from_str::<serde_json::Value>(line) else {
        return;
    };
    let Some(state) = setup_state_from_cli_event(reason, &event, last_step) else {
        return;
    };
    if let Some(phase) = event
        .get("stage")
        .and_then(|value| value.as_str())
        .and_then(|stage| setup_event_phase(source, stage))
    {
        reached_phase.fetch_max(phase, Ordering::AcqRel);
    }
    let _ = channel.send(state);
}

fn is_local_setup_url(url: &tauri::Url) -> bool {
    matches!(
        (url.scheme(), url.host_str()),
        ("tauri", Some("localhost"))
            | ("http", Some("tauri.localhost"))
            | ("https", Some("tauri.localhost"))
    )
}

fn is_hosted_placeholder_url(url: &tauri::Url) -> bool {
    is_local_setup_url(url) && url.path().ends_with("hosted-placeholder.html")
}

fn is_hosted_app_url(url: &tauri::Url, expected_port: Option<u16>) -> bool {
    url.scheme() == "http"
        && url.host_str() == Some("127.0.0.1")
        && expected_port.is_some()
        && url.port() == expected_port
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum HostedNavigation {
    Allow,
    OpenExternal,
    Deny,
}

fn hosted_navigation(url: &tauri::Url, expected_port: Option<u16>) -> HostedNavigation {
    if is_hosted_placeholder_url(url) || is_hosted_app_url(url, expected_port) {
        HostedNavigation::Allow
    } else if matches!(url.scheme(), "http" | "https") {
        HostedNavigation::OpenExternal
    } else {
        HostedNavigation::Deny
    }
}

fn authorize_local_setup(window: &WebviewWindow) -> BridgeResult<()> {
    let url = window
        .url()
        .map_err(|error| BridgeError::new("ORIGIN_DENIED", error.to_string()))?;
    if window.label() != "main" || !is_local_setup_url(&url) {
        return Err(BridgeError::new(
            "ORIGIN_DENIED",
            "Remote content cannot use the lifecycle bridge.",
        ));
    }
    Ok(())
}

fn authorize_hosted(window: &WebviewWindow, host: &HostState) -> BridgeResult<()> {
    let url = window
        .url()
        .map_err(|error| BridgeError::new("ORIGIN_DENIED", error.to_string()))?;
    let expected_port = host.hosted_port.read().ok().and_then(|port| *port);
    if window.label() != "hosted-app" || !is_hosted_app_url(&url, expected_port) {
        return Err(BridgeError::new(
            "ORIGIN_DENIED",
            "Only the active omnideck application can use the desktop bridge.",
        ));
    }
    Ok(())
}

fn publish_update(app: &AppHandle, host: &HostState) {
    let target = host
        .available_update
        .read()
        .ok()
        .and_then(|value| value.clone());
    let deferred = host
        .deferred_version
        .read()
        .ok()
        .and_then(|value| value.clone());
    let payload = target
        .as_ref()
        .map(|target| updates::payload(target, deferred.as_deref()));
    let Ok(encoded) = serde_json::to_string(&payload) else {
        return;
    };
    if let Some(window) = app.get_webview_window("hosted-app") {
        let _ = window.eval(format!(
            "window.dispatchEvent(new CustomEvent('omnideck:update',{{detail:{encoded}}}));"
        ));
    }
}

#[derive(serde::Deserialize)]
struct SoftwareUpdatePreferences {
    software_updates_automatic: Option<bool>,
    software_updates_notify: Option<bool>,
}

async fn remember_update_preferences(host: &HostState) -> BridgeResult<()> {
    let port = host
        .hosted_port
        .read()
        .ok()
        .and_then(|value| *value)
        .or_else(persisted_port)
        .ok_or_else(|| BridgeError::new("PORT_MISSING", "The saved omnideck port is missing."))?;
    let preferences = reqwest::Client::new()
        .get(format!("http://127.0.0.1:{port}/api/settings"))
        .send()
        .await
        .and_then(reqwest::Response::error_for_status)
        .map_err(|error| BridgeError::new("UPDATE_PREFERENCES_FAILED", error.to_string()))?
        .json::<SoftwareUpdatePreferences>()
        .await
        .map_err(|error| BridgeError::new("UPDATE_PREFERENCES_FAILED", error.to_string()))?;
    updates::set_preferences(
        preferences.software_updates_automatic.unwrap_or(true),
        preferences.software_updates_notify.unwrap_or(true),
    )
}

fn window_is_in_sight(app: &AppHandle) -> bool {
    app.get_webview_window("hosted-app").is_some_and(|window| {
        let visible = window.is_visible().unwrap_or(false);
        let minimized = window.is_minimized().unwrap_or(true);
        let expected_port = app
            .state::<HostState>()
            .hosted_port
            .read()
            .ok()
            .and_then(|value| *value);
        visible
            && !minimized
            && window
                .url()
                .is_ok_and(|url| is_hosted_app_url(&url, expected_port))
    })
}

async fn perform_update_check(
    app: &AppHandle,
    host: &HostState,
) -> BridgeResult<Option<updates::UpdateTarget>> {
    let installed = read_setup_record()
        .map(|record| record.image_version)
        .unwrap_or_else(|| {
            image_manifest()
                .map(|manifest| manifest.image_version)
                .unwrap_or_default()
        });
    if installed.is_empty() {
        return Ok(None);
    }
    let previous = updates::read_state();
    let found = updates::check(&installed).await?;
    if let Ok(mut available) = host.available_update.write() {
        *available = found.clone();
    }
    let persisted = updates::read_state();
    if let Ok(mut deferred) = host.deferred_version.write() {
        *deferred = persisted.deferred_version;
    }
    publish_update(app, host);
    if let Some(found) = &found {
        let newly_found = previous.version.as_deref() != Some(found.version.as_str());
        if newly_found && previous.notify && !window_is_in_sight(app) {
            if let Err(error) = app
                .notification()
                .builder()
                .title("An omnideck update is ready")
                .body(format!(
                    "Version {} can be installed from omnideck.",
                    found.version
                ))
                .show()
            {
                platform::append_diagnostic(&format!("[update notification] {error}"));
            }
        }
    }
    Ok(found)
}

fn schedule_update_checks(app: &AppHandle, host: &HostState) {
    if host.update_checks_started.swap(true, Ordering::AcqRel) {
        return;
    }
    let app = app.clone();
    let host = host.clone();
    tauri::async_runtime::spawn(async move {
        tokio::time::sleep(UPDATE_FIRST_CHECK).await;
        loop {
            if let Err(error) = remember_update_preferences(&host).await {
                platform::append_diagnostic(&format!("[update preferences] {}", error.technical()));
            }
            if let Err(error) = perform_update_check(&app, &host).await {
                platform::append_diagnostic(&format!("[update check] {}", error.technical()));
            }
            tokio::time::sleep(UPDATE_INTERVAL).await;
        }
    });
}

fn selected_manifest(host: &HostState) -> BridgeResult<ImageManifest> {
    if let Some(target) = host
        .update_target
        .read()
        .ok()
        .and_then(|value| value.clone())
    {
        return Ok(ImageManifest {
            schema_version: 3,
            app_version: APP_VERSION.into(),
            image_version: target.version,
            image_ref: target.image_ref,
        });
    }
    image_manifest()
}

fn download_feedback_script(
    url: &tauri::Url,
    path: Option<&std::path::Path>,
    success: bool,
) -> String {
    let filename = path
        .and_then(std::path::Path::file_name)
        .and_then(|value| value.to_str())
        .map(str::to_owned)
        .or_else(|| {
            url.path_segments()
                .and_then(|mut segments| segments.next_back())
                .filter(|value| !value.is_empty())
                .map(str::to_owned)
        })
        .unwrap_or_else(|| "download".into());
    let payload = serde_json::json!({ "filename": filename, "success": success });
    format!("window.dispatchEvent(new CustomEvent('omnideck:download',{{detail:{payload}}}));")
}

fn send_state(
    host: &HostState,
    channel: &Channel<SetupState>,
    state: SetupState,
) -> BridgeResult<()> {
    host.app_ready.store(state.can_open, Ordering::Release);
    let mut actions = host.offered_actions.write().map_err(|_| {
        BridgeError::new(
            "STATE_LOCK_FAILED",
            "The recovery action lock was poisoned.",
        )
    })?;
    actions.clear();
    actions.extend(state.primary_action.iter().cloned());
    actions.extend(state.secondary_action.iter().cloned());
    channel
        .send(state)
        .map_err(|error| BridgeError::new("STATE_DELIVERY_FAILED", error.to_string()))
}

fn failure_kind(error: &BridgeError) -> &'static str {
    failure_kind_for(platform::KEY, error)
}

fn should_retry_environment_port(error: &BridgeError, attempt: usize) -> bool {
    error.code == "PORT_IN_USE" && attempt == 0
}

fn port_retry_state(reason: &str, port: u16) -> SetupState {
    parity::working_step(
        reason,
        Some("startup"),
        None,
        Some("Choosing another private address…".into()),
        Some(format!("Port {port} is already in use")),
    )
}

fn failure_kind_for(platform: &str, error: &BridgeError) -> &'static str {
    match error.code.as_str() {
        "RESTART_REQUIRED" => "restart",
        "PERMISSION_CANCELLED" => match platform {
            "win32" => "windowsPermissionCancelled",
            "darwin" => "macosPermissionCancelled",
            _ => "permission",
        },
        "PERMISSION_DENIED" => "permission",
        "WINDOWS_FEATURES_FAILED" => "windowsFeatures",
        "PACKAGE_INDEX_FAILED" => "packageIndex",
        "INSTALLER_FAILED" => match platform {
            "win32" => "windowsInstaller",
            "darwin" => "macosInstaller",
            _ => "linuxInstaller",
        },
        "DOWNLOAD_FAILED" if error.stage.as_deref() == Some("pull_image") => "downloads",
        "DOWNLOAD_FAILED" => "podmanDownload",
        "UNSUPPORTED" => "support",
        "RUNTIME_SETUP_FAILED" | "ENGINE_NOT_FOUND" | "ENGINE_NOT_READY" => "environment",
        "PORT_IN_USE" | "CONTAINER_CONFLICT" | "APP_HEALTH_TIMEOUT" => "startup",
        "INVALID_IMAGE_MANIFEST" => "release",
        "SIDECAR_NOT_BUNDLED"
        | "UNEXPECTED_CLI_VERSION"
        | "UNEXPECTED_SCHEMA_VERSION"
        | "UNEXPECTED_MACHINE"
        | "INVALID_RUNTIME_RESOURCES" => "components",
        _ => "unknown",
    }
}

async fn wait_for_http(port: u16) -> BridgeResult<()> {
    let started = tokio::time::Instant::now();
    loop {
        if let Ok(Ok(mut stream)) = tokio::time::timeout(
            Duration::from_secs(2),
            tokio::net::TcpStream::connect(("127.0.0.1", port)),
        )
        .await
        {
            let request =
                format!("GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n");
            if stream.write_all(request.as_bytes()).await.is_ok() {
                let mut response = [0u8; 64];
                if let Ok(Ok(read)) =
                    tokio::time::timeout(Duration::from_secs(2), stream.read(&mut response)).await
                {
                    let status = std::str::from_utf8(&response[..read])
                        .ok()
                        .and_then(|value| value.lines().next())
                        .and_then(|line| line.split_whitespace().nth(1))
                        .and_then(|value| value.parse::<u16>().ok());
                    if status.is_some_and(|status| (200..300).contains(&status)) {
                        return Ok(());
                    }
                }
            }
        }
        if started.elapsed() >= HEALTH_TIMEOUT {
            return Err(BridgeError::new(
                "APP_HEALTH_TIMEOUT",
                "omnideck did not become ready in time.",
            ));
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
}

fn show_hosted(app: &AppHandle, host: &HostState, port: u16) -> BridgeResult<()> {
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
    schedule_update_checks(app, host);
    Ok(())
}

fn show_setup(app: &AppHandle) -> BridgeResult<()> {
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

fn create_desktop_windows(
    app: &tauri::App,
    hosted_port: Arc<RwLock<Option<u16>>>,
) -> tauri::Result<()> {
    WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("omnideck")
        .background_color(Color(12, 14, 20, 255))
        .inner_size(1280.0, 820.0)
        .min_inner_size(880.0, 620.0)
        .initialization_script(ZOOM_CONTROL_SCRIPT)
        .on_navigation(is_local_setup_url)
        .on_new_window(|_, _| NewWindowResponse::Deny)
        .build()?;

    let navigation_port = hosted_port.clone();
    let new_window_port = hosted_port;
    let app_handle = app.handle().clone();
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
    .enable_clipboard_access()
    .initialization_script(ZOOM_CONTROL_SCRIPT)
    .initialization_script(HOSTED_BRIDGE_SCRIPT)
    .on_download(|webview, event| {
        if let DownloadEvent::Finished { url, path, success } = event {
            let _ = webview.eval(download_feedback_script(&url, path.as_deref(), success));
        }
        true
    })
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

#[tauri::command]
async fn bootstrap(
    app: AppHandle,
    window: WebviewWindow,
    host: tauri::State<'_, HostState>,
    on_event: Channel<SetupState>,
) -> BridgeResult<BootstrapResult> {
    authorize_local_setup(&window)?;
    let Some(record) = read_setup_record() else {
        send_state(&host, &on_event, parity::welcome())?;
        show_setup(&app)?;
        return Ok(BootstrapResult {
            action: "welcome",
            reason: "first-run".into(),
        });
    };
    let reason = if record.status == "in-progress" {
        "resume".to_owned()
    } else {
        record.reason.clone()
    };
    *host.setup_reason.write().map_err(|_| {
        BridgeError::new("STATE_LOCK_FAILED", "The setup reason lock was poisoned.")
    })? = reason.clone();
    if record.status == "in-progress" {
        send_state(&host, &on_event, parity::working(&reason, None, 0.0))?;
        show_setup(&app)?;
        return Ok(BootstrapResult {
            action: "setup",
            reason,
        });
    }

    if host
        .update_target
        .read()
        .ok()
        .is_some_and(|target| target.is_none())
    {
        if let Some(target) = updates::pending_at_launch(&record.image_version) {
            if let Ok(mut selected) = host.update_target.write() {
                *selected = Some(target);
            }
        }
    }
    if host
        .update_target
        .read()
        .ok()
        .is_some_and(|target| target.is_some())
    {
        *host.setup_reason.write().map_err(|_| {
            BridgeError::new("STATE_LOCK_FAILED", "The setup reason lock was poisoned.")
        })? = "update".into();
        send_state(&host, &on_event, parity::working("update", None, 0.0))?;
        show_setup(&app)?;
        return Ok(BootstrapResult {
            action: "setup",
            reason: "update".into(),
        });
    }

    let result = async {
        validate_bundled_cli(&app).await?;
        let runtime = runtime_status(&app).await?;
        if !runtime.ready {
            return Err(BridgeError::new(
                "ENGINE_NOT_READY",
                "The secure environment is not ready.",
            ));
        }
        let manifest = image_manifest()?;
        let installed_is_newer =
            updates::is_newer_release(&record.image_version, &manifest.image_version);
        if record.app_version != APP_VERSION
            || (!installed_is_newer
                && (record.image_version != manifest.image_version
                    || record.image_ref != manifest.image_ref))
        {
            *host.setup_reason.write().map_err(|_| {
                BridgeError::new("STATE_LOCK_FAILED", "The setup reason lock was poisoned.")
            })? = "update".into();
            send_state(&host, &on_event, parity::working("update", None, 0.0))?;
            show_setup(&app)?;
            return Ok(BootstrapResult {
                action: "setup",
                reason: "update".into(),
            });
        }
        let expected_port = persisted_port().ok_or_else(|| {
            BridgeError::new("PORT_MISSING", "The saved omnideck port is missing.")
        })?;
        let mut status = instance_status(&app).await?;
        if status.image != record.image_ref
            || status.web_ui_port.parse::<u16>().ok() != Some(expected_port)
        {
            *host.setup_reason.write().map_err(|_| {
                BridgeError::new("STATE_LOCK_FAILED", "The setup reason lock was poisoned.")
            })? = "repair".into();
            send_state(&host, &on_event, parity::working("repair", None, 0.0))?;
            show_setup(&app)?;
            return Ok(BootstrapResult {
                action: "setup",
                reason: "repair".into(),
            });
        }
        if status.status != "running" {
            let started = require_success(
                run_fixed(&app, FixedOperation::StartInstance).await?,
                "Start application environment",
            )?;
            status = parse_instance_status(&started.stdout)?;
        }
        let port = status
            .web_ui_port
            .parse::<u16>()
            .map_err(|error| BridgeError::new("INVALID_APP_PORT", error.to_string()))?;
        wait_for_http(port).await?;
        show_hosted(&app, &host, port)?;
        Ok(BootstrapResult {
            action: "open",
            reason: record.reason,
        })
    }
    .await;

    match result {
        Ok(value) => Ok(value),
        Err(error) => {
            platform::append_diagnostic(&format!("[bootstrap failure] {}", error.technical()));
            let reached = parity::phase_index("startup").unwrap_or(3);
            send_state(
                &host,
                &on_event,
                parity::error(failure_kind(&error), &reason, reached, error.technical()),
            )?;
            show_setup(&app)?;
            Ok(BootstrapResult {
                action: "doctor",
                reason,
            })
        }
    }
}

#[tauri::command]
async fn begin_setup(
    app: AppHandle,
    window: WebviewWindow,
    host: tauri::State<'_, HostState>,
    on_event: Channel<SetupState>,
) -> BridgeResult<()> {
    authorize_local_setup(&window)?;
    if host.setup_running.swap(true, Ordering::AcqRel) {
        return Ok(());
    }
    let reason = host
        .setup_reason
        .read()
        .map(|value| value.clone())
        .unwrap_or_else(|_| "resume".into());
    let reached_phase = Arc::new(AtomicUsize::new(0));
    let result = async {
        let manifest = selected_manifest(&host)?;
        save_setup_record("in-progress", &reason, &manifest)?;
        send_state(
            &host,
            &on_event,
            parity::working_step(
                &reason,
                Some(parity::first_step()),
                None,
                None,
                Some("Starting setup".into()),
            ),
        )?;
        validate_bundled_cli(&app).await?;

        let mut runtime = runtime_status(&app).await?;
        if !runtime.ready {
            let channel = on_event.clone();
            let reason_for_events = reason.clone();
            let reached_phase_for_events = reached_phase.clone();
            let mut last_step = None;
            let ensured = run_cli(
                &app,
                FixedOperation::RuntimeEnsure.args(),
                SETUP_TIMEOUT,
                move |line| {
                    forward_setup_event(
                        line,
                        &reason_for_events,
                        &mut last_step,
                        &reached_phase_for_events,
                        &channel,
                        SetupEventSource::Runtime,
                    );
                },
            )
            .await?;
            require_success(ensured, "Shared runtime setup")?;
            runtime = runtime_status(&app).await?;
            if !runtime.ready {
                return Err(BridgeError::new(
                    "RUNTIME_SETUP_FAILED",
                    "Podman setup finished, but the Omnideck runtime is not ready.",
                ));
            }
        }

        if let Some(environment) = parity::phase_index("environment") {
            reached_phase.fetch_max(environment, Ordering::AcqRel);
            send_state(
                &host,
                &on_event,
                parity::working_step(
                    &reason,
                    Some("secure-space"),
                    Some(1.0),
                    Some("Preparing a secure space to run in…".into()),
                    Some("Secure space ready".into()),
                ),
            )?;
        }
        let mut port = reserve_and_persist_port(false)?;
        let memory = runtime.resources.container.memory.clone();
        let shm_size = runtime.resources.container.shm_size.clone();
        for attempt in 0..2 {
            let port_text = port.to_string();
            let args = vec![
                "--json".into(),
                "--name".into(),
                platform::resource_name(CONTAINER_NAME),
                "environment".into(),
                "ensure".into(),
                "--image".into(),
                manifest.image_ref.clone(),
                "--port".into(),
                port_text,
                "--memory".into(),
                memory.clone(),
                "--shm-size".into(),
                shm_size.clone(),
                "--home-volume".into(),
                platform::resource_name(HOME_VOLUME),
                "--state-volume".into(),
                platform::resource_name(STATE_VOLUME),
            ];
            let channel = on_event.clone();
            let reason_for_events = reason.clone();
            let reached_phase_for_events = reached_phase.clone();
            let mut last_step = Some("app-download".to_owned());
            let environment = run_cli(&app, args, SETUP_TIMEOUT, move |line| {
                forward_setup_event(
                    line,
                    &reason_for_events,
                    &mut last_step,
                    &reached_phase_for_events,
                    &channel,
                    SetupEventSource::Environment,
                );
            })
            .await?;
            match require_success(environment, "Reconcile application environment") {
                Ok(_) => break,
                Err(error) if should_retry_environment_port(&error, attempt) => {
                    send_state(&host, &on_event, port_retry_state(&reason, port))?;
                    tokio::time::sleep(Duration::from_secs(1)).await;
                    port = reserve_and_persist_port(true)?;
                }
                Err(error) => return Err(error),
            }
        }

        send_state(
            &host,
            &on_event,
            parity::working_step(
                &reason,
                Some("startup"),
                Some(0.5),
                Some("Starting omnideck and checking its connection…".into()),
                Some("Checking 127.0.0.1".into()),
            ),
        )?;
        reached_phase.fetch_max(
            parity::phase_index("startup").unwrap_or(0),
            Ordering::AcqRel,
        );
        let status = instance_status(&app).await?;
        let actual_port = status
            .web_ui_port
            .parse::<u16>()
            .map_err(|error| BridgeError::new("INVALID_APP_PORT", error.to_string()))?;
        wait_for_http(actual_port).await?;
        save_setup_record("complete", &reason, &manifest)?;
        if reason == "update" {
            updates::complete()?;
            if let Ok(mut selected) = host.update_target.write() {
                *selected = None;
            }
            if let Ok(mut available) = host.available_update.write() {
                *available = None;
            }
            if let Ok(mut deferred) = host.deferred_version.write() {
                *deferred = None;
            }
        }
        *host.hosted_port.write().map_err(|_| {
            BridgeError::new("STATE_LOCK_FAILED", "The hosted origin lock was poisoned.")
        })? = Some(actual_port);
        send_state(&host, &on_event, parity::ready(&reason))?;
        Ok(())
    }
    .await;
    host.setup_running.store(false, Ordering::Release);
    if let Err(error) = result {
        platform::append_diagnostic(&format!("[setup failure] {}", error.technical()));
        send_state(
            &host,
            &on_event,
            parity::error(
                failure_kind(&error),
                &reason,
                reached_phase.load(Ordering::Acquire),
                error.technical(),
            ),
        )?;
    }
    Ok(())
}

#[tauri::command]
async fn open_app(
    app: AppHandle,
    window: WebviewWindow,
    host: tauri::State<'_, HostState>,
) -> BridgeResult<()> {
    authorize_local_setup(&window)?;
    if !host.app_ready.load(Ordering::Acquire) {
        return Err(BridgeError::new(
            "ACTION_DENIED",
            "omnideck has not finished setup.",
        ));
    }
    let port = host
        .hosted_port
        .read()
        .ok()
        .and_then(|value| *value)
        .or_else(persisted_port)
        .ok_or_else(|| BridgeError::new("PORT_MISSING", "The saved omnideck port is missing."))?;
    wait_for_http(port).await?;
    show_hosted(&app, &host, port)
}

#[tauri::command]
fn run_action(
    app: AppHandle,
    window: WebviewWindow,
    host: tauri::State<'_, HostState>,
    action: String,
) -> BridgeResult<()> {
    authorize_local_setup(&window)?;
    if !host
        .offered_actions
        .read()
        .map_err(|_| {
            BridgeError::new(
                "STATE_LOCK_FAILED",
                "The recovery action lock was poisoned.",
            )
        })?
        .contains(&action)
    {
        return Err(BridgeError::new(
            "ACTION_DENIED",
            "That recovery action is not available right now.",
        ));
    }
    match action.as_str() {
        "close" => {
            app.exit(0);
            Ok(())
        }
        "supported-systems" => platform::open_url(SUPPORTED_SYSTEMS_URL),
        "download" => platform::open_url(DOWNLOAD_URL),
        "restart" => {
            platform::restart_computer()?;
            app.exit(0);
            Ok(())
        }
        _ => Err(BridgeError::new(
            "ACTION_DENIED",
            "The requested recovery action is not allowed.",
        )),
    }
}

#[tauri::command]
fn current_update(
    window: WebviewWindow,
    host: tauri::State<'_, HostState>,
) -> BridgeResult<Option<updates::UpdatePayload>> {
    authorize_hosted(&window, &host)?;
    let target = host
        .available_update
        .read()
        .map_err(|_| BridgeError::new("STATE_LOCK_FAILED", "The update lock was poisoned."))?
        .clone();
    let deferred = host
        .deferred_version
        .read()
        .map_err(|_| BridgeError::new("STATE_LOCK_FAILED", "The update lock was poisoned."))?
        .clone();
    Ok(target
        .as_ref()
        .map(|target| updates::payload(target, deferred.as_deref())))
}

#[tauri::command]
async fn check_for_update(
    app: AppHandle,
    window: WebviewWindow,
    host: tauri::State<'_, HostState>,
) -> BridgeResult<Option<updates::UpdatePayload>> {
    authorize_hosted(&window, &host)?;
    remember_update_preferences(&host).await?;
    perform_update_check(&app, &host).await?;
    current_update(window, host)
}

fn available_update(host: &HostState) -> BridgeResult<updates::UpdateTarget> {
    host.available_update
        .read()
        .map_err(|_| BridgeError::new("STATE_LOCK_FAILED", "The update lock was poisoned."))?
        .clone()
        .ok_or_else(|| BridgeError::new("UPDATE_MISSING", "There is no update to act on."))
}

#[tauri::command]
fn defer_update(
    app: AppHandle,
    window: WebviewWindow,
    host: tauri::State<'_, HostState>,
) -> BridgeResult<()> {
    authorize_hosted(&window, &host)?;
    let target = available_update(&host)?;
    updates::defer(&target)?;
    *host
        .deferred_version
        .write()
        .map_err(|_| BridgeError::new("STATE_LOCK_FAILED", "The update lock was poisoned."))? =
        Some(target.version);
    publish_update(&app, &host);
    Ok(())
}

#[tauri::command]
fn skip_update(
    app: AppHandle,
    window: WebviewWindow,
    host: tauri::State<'_, HostState>,
) -> BridgeResult<()> {
    authorize_hosted(&window, &host)?;
    let target = available_update(&host)?;
    updates::skip(&target)?;
    *host
        .available_update
        .write()
        .map_err(|_| BridgeError::new("STATE_LOCK_FAILED", "The update lock was poisoned."))? =
        None;
    *host
        .deferred_version
        .write()
        .map_err(|_| BridgeError::new("STATE_LOCK_FAILED", "The update lock was poisoned."))? =
        None;
    publish_update(&app, &host);
    Ok(())
}

#[tauri::command]
fn install_update(
    app: AppHandle,
    window: WebviewWindow,
    host: tauri::State<'_, HostState>,
) -> BridgeResult<()> {
    authorize_hosted(&window, &host)?;
    let target = available_update(&host)?;
    *host
        .update_target
        .write()
        .map_err(|_| BridgeError::new("STATE_LOCK_FAILED", "The update lock was poisoned."))? =
        Some(target);
    *host.setup_reason.write().map_err(|_| {
        BridgeError::new("STATE_LOCK_FAILED", "The setup reason lock was poisoned.")
    })? = "update".into();
    host.app_ready.store(false, Ordering::Release);
    let setup = app
        .get_webview_window("main")
        .ok_or_else(|| BridgeError::new("WINDOW_MISSING", "The setup window is unavailable."))?;
    setup
        .reload()
        .map_err(|error| BridgeError::new("WINDOW_UPDATE_FAILED", error.to_string()))?;
    show_setup(&app)
}

fn record_packaged_smoke(status: &RuntimeStatus) -> BridgeResult<()> {
    let Some(path) = std::env::var_os("OMNIDECK_DESKTOP_SMOKE_FILE") else {
        return Ok(());
    };
    let proof = serde_json::json!({
        "cliVersion": EXPECTED_CLI_VERSION,
        "cliCommit": EXPECTED_CLI_COMMIT,
        "schemaVersion": status.schema_version,
        "runtime": status.runtime,
        "state": status.state,
        "ready": status.ready,
        "operations": ["--version", "--json runtime status"],
        "mutation": false
    });
    fs::write(
        path,
        serde_json::to_vec_pretty(&proof)
            .map_err(|error| BridgeError::new("SMOKE_PROOF_FAILED", error.to_string()))?,
    )
    .map_err(|error| BridgeError::new("SMOKE_PROOF_FAILED", error.to_string()))
}

async fn run_packaged_smoke(app: AppHandle) -> BridgeResult<()> {
    validate_bundled_cli(&app).await?;
    let status = runtime_status(&app).await?;
    record_packaged_smoke(&status)
}

fn record_smoke_error(error: &BridgeError) {
    let Some(path) = std::env::var_os("OMNIDECK_DESKTOP_SMOKE_FILE") else {
        return;
    };
    let proof =
        serde_json::json!({ "stage": "host-smoke-failed", "error": error, "mutation": false });
    if let Ok(encoded) = serde_json::to_vec_pretty(&proof) {
        let _ = fs::write(path, encoded);
    }
}

pub fn run() {
    let host = HostState::default();
    let window_port = host.hosted_port.clone();
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            let active = app
                .get_webview_window("hosted-app")
                .filter(|window| window.is_visible().unwrap_or(false))
                .or_else(|| app.get_webview_window("main"));
            if let Some(window) = active {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .manage(host)
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            bootstrap,
            begin_setup,
            open_app,
            run_action,
            current_update,
            check_for_update,
            install_update,
            defer_update,
            skip_update
        ])
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::CloseRequested { .. }) {
                // Both webviews are created up front and one is always hidden. Exiting
                // here prevents that hidden companion from leaving a headless process.
                window.app_handle().exit(0);
            }
        })
        .setup(move |app| {
            create_desktop_windows(app, window_port.clone())?;
            if std::env::var_os("OMNIDECK_DESKTOP_SMOKE_FILE").is_some() {
                let handle = app.handle().clone();
                tauri::async_runtime::spawn(async move {
                    if let Err(error) = run_packaged_smoke(handle).await {
                        record_smoke_error(&error);
                    }
                });
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running omnideck");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hosted_origin_is_dynamic_and_exact() {
        let url = "http://127.0.0.1:51208/settings".parse().unwrap();
        assert!(is_hosted_app_url(&url, Some(51208)));
        assert!(!is_hosted_app_url(&url, Some(51209)));
        assert!(!is_hosted_app_url(
            &"http://localhost:51208/".parse().unwrap(),
            Some(51208)
        ));
        assert!(!is_hosted_app_url(
            &"https://127.0.0.1:51208/".parse().unwrap(),
            Some(51208)
        ));
    }

    #[test]
    fn hosted_navigation_keeps_the_app_local_and_opens_web_links_externally() {
        assert_eq!(
            hosted_navigation(
                &"http://127.0.0.1:51208/settings".parse().unwrap(),
                Some(51208)
            ),
            HostedNavigation::Allow
        );
        assert_eq!(
            hosted_navigation(&"https://example.com/help".parse().unwrap(), Some(51208)),
            HostedNavigation::OpenExternal
        );
        assert_eq!(
            hosted_navigation(&"mailto:help@example.com".parse().unwrap(), Some(51208)),
            HostedNavigation::Deny
        );
    }

    #[test]
    fn permission_cancellation_copy_is_platform_specific() {
        let error = BridgeError::new("PERMISSION_CANCELLED", "approval cancelled");
        assert_eq!(
            failure_kind_for("win32", &error),
            "windowsPermissionCancelled"
        );
        assert_eq!(
            failure_kind_for("darwin", &error),
            "macosPermissionCancelled"
        );

        let installer = BridgeError::new("INSTALLER_FAILED", "installer failed");
        assert_eq!(failure_kind_for("win32", &installer), "windowsInstaller");
        assert_eq!(failure_kind_for("darwin", &installer), "macosInstaller");
        assert_eq!(failure_kind_for("linux", &installer), "linuxInstaller");
    }

    #[test]
    fn mac_machine_switch_copy_is_visible_and_wording_locked() {
        let explanation = "macOS can run only one Podman machine at a time. Stopping \"podman-machine-default\" keeps its files but also stops its running containers.";
        let event = serde_json::json!({
            "stage": "environment",
            "substage": "secure-space",
            "state": "start",
            "activity": "Preparing a secure space to run in…",
            "status": "Switching Podman machines",
            "detail": explanation,
        });
        let state = setup_state_from_cli_event("repair", &event, &mut None).unwrap();
        assert_eq!(state.status.as_deref(), Some("Switching Podman machines"));
        assert_eq!(state.activity.as_deref(), Some(explanation));
    }

    #[test]
    fn a_classified_port_conflict_gets_one_automatic_retry() {
        let conflict = BridgeError::new(
            "PORT_IN_USE",
            "another Omnideck installation already uses port 2337",
        );
        assert!(should_retry_environment_port(&conflict, 0));
        assert!(!should_retry_environment_port(&conflict, 1));
        assert!(!should_retry_environment_port(
            &BridgeError::new("INTERNAL_ERROR", "unclassified failure"),
            0
        ));
    }

    #[test]
    fn interrupted_update_resumes_the_selected_immutable_image() {
        let image_ref = format!("ghcr.io/omnideck-dev/omnideck@sha256:{}", "a".repeat(64));
        let target =
            interrupted_update_target("in-progress", "update", "0.1.2", &image_ref).unwrap();
        assert_eq!(target.version, "0.1.2");
        assert_eq!(target.image_ref, image_ref);
        assert!(interrupted_update_target("complete", "update", "0.1.2", "unused").is_none());
        assert!(interrupted_update_target("in-progress", "repair", "0.1.2", "unused").is_none());
    }

    #[test]
    fn port_conflict_recovery_copy_is_wording_locked() {
        let state = port_retry_state("repair", 2337);
        assert_eq!(state.stage, "preparing");
        assert_eq!(state.step, parity::step_index("startup"));
        assert!(state.indeterminate);
        assert_eq!(
            state.activity.as_deref(),
            Some("Choosing another private address…")
        );
        assert_eq!(state.status.as_deref(), Some("Port 2337 is already in use"));
        assert!(!state.can_retry);
    }
}

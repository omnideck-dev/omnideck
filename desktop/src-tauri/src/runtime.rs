use crate::cli::{
    instance_status, parse_instance_status, require_success, run_cli, run_fixed, runtime_status,
    validate_bundled_cli, FixedOperation, RuntimeStatus, EXPECTED_CLI_COMMIT, EXPECTED_CLI_VERSION,
    SETUP_TIMEOUT,
};
use crate::parity::SetupState;
use crate::state::{
    image_manifest, persisted_port, read_setup_record, reserve_and_persist_port, save_setup_record,
    ImageManifest, APP_VERSION,
};
use crate::{
    navigation::authorize_local_setup,
    parity, platform, updates,
    windows::{show_hosted, show_setup},
};
use serde::Serialize;
use std::{
    collections::HashSet,
    fmt, fs,
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc, RwLock,
    },
    time::Duration,
};
use tauri::{ipc::Channel, AppHandle, WebviewWindow};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

pub(crate) const CONTAINER_NAME: &str = "omnideck-desktop";
const HOME_VOLUME: &str = "omnideck-desktop-home";
const STATE_VOLUME: &str = "omnideck-desktop-state";
const DOWNLOAD_URL: &str = "https://github.com/omnideck-dev/omnideck/releases";
const SUPPORTED_SYSTEMS_URL: &str = "https://github.com/omnideck-dev/omnideck#prerequisites";
const HEALTH_TIMEOUT: Duration = Duration::from_secs(120);

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct BridgeError {
    pub(crate) code: String,
    pub(crate) message: String,
    pub(crate) stderr: Option<String>,
    pub(crate) stage: Option<String>,
}

impl BridgeError {
    pub(crate) fn new(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
            stderr: None,
            stage: None,
        }
    }

    pub(crate) fn with_stderr(mut self, stderr: String) -> Self {
        if !stderr.trim().is_empty() {
            self.stderr = Some(stderr);
        }
        self
    }

    pub(crate) fn technical(&self) -> String {
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
pub(crate) type BridgeResult<T> = Result<T, BridgeError>;

#[derive(Debug, Serialize)]
pub(crate) struct BootstrapResult {
    action: &'static str,
    reason: String,
}

#[derive(Clone)]
pub(crate) struct HostState {
    pub(crate) hosted_port: Arc<RwLock<Option<u16>>>,
    pub(crate) setup_reason: Arc<RwLock<String>>,
    pub(crate) setup_running: Arc<AtomicBool>,
    pub(crate) app_ready: Arc<AtomicBool>,
    pub(crate) offered_actions: Arc<RwLock<HashSet<String>>>,
    pub(crate) available_update: Arc<RwLock<Option<updates::UpdateTarget>>>,
    pub(crate) deferred_version: Arc<RwLock<Option<String>>>,
    pub(crate) update_target: Arc<RwLock<Option<updates::UpdateTarget>>>,
    pub(crate) update_checks_started: Arc<AtomicBool>,
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

#[tauri::command]
pub(crate) async fn bootstrap(
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
pub(crate) async fn begin_setup(
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
pub(crate) async fn open_app(
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
pub(crate) fn run_action(
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

pub(crate) fn start_packaged_smoke(app: AppHandle) {
    if std::env::var_os("OMNIDECK_DESKTOP_SMOKE_FILE").is_none() {
        return;
    }
    tauri::async_runtime::spawn(async move {
        if let Err(error) = run_packaged_smoke(app).await {
            record_smoke_error(&error);
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

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

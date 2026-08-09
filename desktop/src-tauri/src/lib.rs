mod parity;
mod platform;

use parity::SetupState;
use serde::{Deserialize, Serialize};
use std::{
    collections::HashSet,
    fmt, fs,
    net::TcpListener,
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc, RwLock,
    },
    time::Duration,
};
use tauri::{
    ipc::Channel, webview::NewWindowResponse, AppHandle, Manager, WebviewUrl, WebviewWindow,
    WebviewWindowBuilder,
};
use tauri_plugin_shell::{process::CommandEvent, ShellExt};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

const EXPECTED_SCHEMA_VERSION: u32 = 4;
const EXPECTED_CLI_VERSION: &str = "v0.11.0-alpha.1";
const EXPECTED_CLI_COMMIT: &str = "48434a5f82c0";
const APP_VERSION: &str = "0.1.0-alpha.9";
const DEFAULT_APP_PORT: u16 = 2338;
const CONTAINER_NAME: &str = "omnideck-desktop";
const HOME_VOLUME: &str = "omnideck-desktop-home";
const STATE_VOLUME: &str = "omnideck-desktop-state";
const DOWNLOAD_URL: &str = "https://github.com/omnideck-dev/omnideck/releases";
const SUPPORTED_SYSTEMS_URL: &str = "https://github.com/omnideck-dev/omnideck#prerequisites";
const STDOUT_LIMIT: usize = 1_000_000;
const STDERR_LIMIT: usize = 256 * 1024;
const INSPECTION_TIMEOUT: Duration = Duration::from_secs(15);
const SETUP_TIMEOUT: Duration = Duration::from_secs(20 * 60);
const HEALTH_TIMEOUT: Duration = Duration::from_secs(120);
const HOSTED_SHORTCUTS_SCRIPT: &str = r#"
(() => {
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

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum FixedOperation {
    Version,
    RuntimeStatus,
    RuntimeEnsure,
    InstanceStatus,
    StartInstance,
}

impl FixedOperation {
    fn args(self) -> Vec<String> {
        let values: &[&str] = match self {
            Self::Version => &["--version"],
            Self::RuntimeStatus => &["--json", "runtime", "status"],
            Self::RuntimeEnsure => &["--json", "runtime", "ensure"],
            Self::InstanceStatus => {
                return vec![
                    "--json".into(),
                    "--name".into(),
                    platform::resource_name(CONTAINER_NAME),
                    "status".into(),
                ];
            }
            Self::StartInstance => {
                return vec![
                    "--json".into(),
                    "--name".into(),
                    platform::resource_name(CONTAINER_NAME),
                    "start".into(),
                ];
            }
        };
        values.iter().map(|value| (*value).to_owned()).collect()
    }

    fn timeout(self) -> Duration {
        match self {
            Self::RuntimeEnsure | Self::StartInstance => SETUP_TIMEOUT,
            _ => INSPECTION_TIMEOUT,
        }
    }
}

#[derive(Debug)]
struct ProcessResult {
    exit_code: i32,
    stdout: String,
    stderr: String,
}

#[derive(Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
struct CliVersion {
    version: String,
    commit: String,
    raw: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeStatus {
    schema_version: u32,
    runtime: String,
    state: String,
    ready: bool,
    path: Option<String>,
    version: Option<String>,
    machine_name: Option<String>,
    phase: Option<String>,
    activity: Option<String>,
    resources: RuntimeResources,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeResources {
    container: ContainerResources,
    machine: MachineResources,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct ContainerResources {
    memory: String,
    shm_size: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct MachineResources {
    mode: String,
    memory_mb: Option<f64>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct InstanceStatus {
    container: String,
    status: String,
    image: String,
    web_ui_port: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SetupRecord {
    schema_version: u32,
    status: String,
    reason: String,
    app_version: String,
    image_version: String,
    image_ref: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct SetupRecordWrite<'a> {
    schema_version: u32,
    status: &'a str,
    reason: &'a str,
    app_version: &'a str,
    image_version: &'a str,
    image_ref: &'a str,
    image_digest: &'a str,
    updated_at: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ImageManifest {
    schema_version: u32,
    app_version: String,
    image_version: String,
    image_ref: String,
}

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
}

impl Default for HostState {
    fn default() -> Self {
        Self {
            hosted_port: Arc::new(RwLock::new(None)),
            setup_reason: Arc::new(RwLock::new("first-run".into())),
            setup_running: Arc::new(AtomicBool::new(false)),
            app_ready: Arc::new(AtomicBool::new(false)),
            offered_actions: Arc::new(RwLock::new(HashSet::new())),
        }
    }
}

fn append_bounded(
    destination: &mut Vec<u8>,
    chunk: &[u8],
    limit: usize,
    stream: &str,
) -> BridgeResult<()> {
    if destination.len().saturating_add(chunk.len()) > limit {
        return Err(BridgeError::new(
            "OUTPUT_LIMIT",
            format!("The bundled CLI exceeded the {stream} output limit."),
        ));
    }
    destination.extend_from_slice(chunk);
    Ok(())
}

#[derive(Default)]
struct LineBuffer {
    pending: Vec<u8>,
}

impl LineBuffer {
    fn push<F>(&mut self, chunk: &[u8], on_line: &mut F)
    where
        F: FnMut(&str),
    {
        self.pending.extend_from_slice(chunk);
        while let Some(index) = self.pending.iter().position(|byte| *byte == b'\n') {
            let mut line: Vec<u8> = self.pending.drain(..=index).collect();
            line.pop();
            if line.last() == Some(&b'\r') {
                line.pop();
            }
            Self::deliver(&line, on_line);
        }
    }

    fn flush<F>(&mut self, on_line: &mut F)
    where
        F: FnMut(&str),
    {
        let pending = std::mem::take(&mut self.pending);
        Self::deliver(&pending, on_line);
    }

    fn deliver<F>(line: &[u8], on_line: &mut F)
    where
        F: FnMut(&str),
    {
        let text = String::from_utf8_lossy(line);
        let text = text.trim();
        if !text.is_empty() {
            on_line(text);
        }
    }
}

async fn run_cli<F>(
    app: &AppHandle,
    args: Vec<String>,
    timeout_duration: Duration,
    mut on_stdout: F,
) -> BridgeResult<ProcessResult>
where
    F: FnMut(&str),
{
    let command = app
        .shell()
        .sidecar("omnideck-cli")
        .map_err(|error| BridgeError::new("SIDECAR_NOT_BUNDLED", error.to_string()))?
        .args(args);
    let (mut events, child) = command
        .spawn()
        .map_err(|error| BridgeError::new("SIDECAR_SPAWN_FAILED", error.to_string()))?;
    let mut stdout = Vec::new();
    let mut stderr = Vec::new();
    let mut stdout_lines = LineBuffer::default();
    let mut timeout = Box::pin(tokio::time::sleep(timeout_duration));

    loop {
        tokio::select! {
            _ = &mut timeout => {
                let _ = child.kill();
                return Err(BridgeError::new("SIDECAR_TIMEOUT", "The bundled CLI did not finish in time."));
            }
            event = events.recv() => match event {
                Some(CommandEvent::Stdout(line)) => {
                    if let Err(error) = append_bounded(&mut stdout, &line, STDOUT_LIMIT, "stdout") {
                        let _ = child.kill();
                        return Err(error);
                    }
                    stdout_lines.push(&line, &mut on_stdout);
                }
                Some(CommandEvent::Stderr(line)) => {
                    if let Err(error) = append_bounded(&mut stderr, &line, STDERR_LIMIT, "stderr") {
                        let _ = child.kill();
                        return Err(error);
                    }
                }
                Some(CommandEvent::Error(error)) => {
                    let _ = child.kill();
                    return Err(BridgeError::new("SIDECAR_IO_FAILED", error));
                }
                Some(CommandEvent::Terminated(payload)) => {
                    stdout_lines.flush(&mut on_stdout);
                    return Ok(ProcessResult {
                        exit_code: payload.code.unwrap_or(-1),
                        stdout: String::from_utf8_lossy(&stdout).trim().to_owned(),
                        stderr: String::from_utf8_lossy(&stderr).trim().to_owned(),
                    });
                }
                Some(_) => {}
                None => {
                    let _ = child.kill();
                    return Err(BridgeError::new("SIDECAR_IO_FAILED", "The bundled CLI event stream ended before process completion."));
                }
            }
        }
    }
}

async fn run_fixed(app: &AppHandle, operation: FixedOperation) -> BridgeResult<ProcessResult> {
    run_cli(app, operation.args(), operation.timeout(), |_| {}).await
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
    let status = event
        .get("status")
        .and_then(|value| value.as_str())
        .or_else(|| event.get("detail").and_then(|value| value.as_str()))
        .map(str::to_owned)
        .filter(|value| !value.is_empty());
    let progress = if state == "done" { Some(1.0) } else { progress };
    Some(parity::working_step(
        reason,
        step.as_deref(),
        progress,
        activity,
        status,
    ))
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

fn parse_cli_version(raw: &str) -> BridgeResult<CliVersion> {
    let fields: Vec<_> = raw.split_whitespace().collect();
    if fields.len() < 4 || fields[0] != "omnideck" || fields[1] != "version" {
        return Err(BridgeError::new(
            "INVALID_VERSION_OUTPUT",
            "The bundled CLI returned an unrecognized version string.",
        ));
    }
    let version = fields[2];
    let commit = fields[3].trim_matches(['(', ')']);
    if version != EXPECTED_CLI_VERSION || commit != EXPECTED_CLI_COMMIT {
        return Err(BridgeError::new("UNEXPECTED_CLI_VERSION", format!(
            "Expected {EXPECTED_CLI_VERSION} ({EXPECTED_CLI_COMMIT}), received {version} ({commit})."
        )));
    }
    Ok(CliVersion {
        version: version.into(),
        commit: commit.into(),
        raw: raw.into(),
    })
}

fn parse_runtime_status(raw: &str) -> BridgeResult<RuntimeStatus> {
    let status: RuntimeStatus = serde_json::from_str(raw).map_err(|error| {
        cli_error(raw).unwrap_or_else(|| {
            BridgeError::new(
                "INVALID_RUNTIME_JSON",
                format!("The bundled CLI returned malformed runtime JSON: {error}"),
            )
        })
    })?;
    if status.schema_version != EXPECTED_SCHEMA_VERSION {
        return Err(BridgeError::new(
            "UNEXPECTED_SCHEMA_VERSION",
            format!(
                "Expected runtime schema {EXPECTED_SCHEMA_VERSION}, received {}.",
                status.schema_version
            ),
        ));
    }
    if status.runtime != "podman" {
        return Err(BridgeError::new(
            "UNEXPECTED_RUNTIME",
            format!("Expected Podman, received {}.", status.runtime),
        ));
    }
    if status.state.trim().is_empty() {
        return Err(BridgeError::new(
            "INVALID_RUNTIME_JSON",
            "The bundled CLI returned an invalid runtime state.",
        ));
    }
    let container_memory = resource_memory_mb(&status.resources.container.memory);
    let shared_memory = resource_memory_mb(&status.resources.container.shm_size);
    if container_memory.is_none()
        || shared_memory.is_none()
        || shared_memory > container_memory
        || status.resources.machine.mode.trim().is_empty()
    {
        return Err(BridgeError::new(
            "INVALID_RUNTIME_RESOURCES",
            "The bundled CLI returned invalid resource defaults.",
        ));
    }
    if status.resources.machine.mode == "podman-managed"
        && status.resources.machine.memory_mb.is_none_or(|memory| {
            !memory.is_finite() || memory < container_memory.unwrap_or(0.0) + 2048.0
        })
    {
        return Err(BridgeError::new(
            "INVALID_RUNTIME_RESOURCES",
            "The Podman machine memory limit is too small for the application environment.",
        ));
    }
    if status.ready
        && platform::uses_managed_machine()
        && status.machine_name.as_deref() != Some(platform::machine_name().as_str())
    {
        let expected = platform::machine_name();
        return Err(BridgeError::new(
            "UNEXPECTED_MACHINE",
            format!(
                "Expected Podman machine {expected}, received {}.",
                status.machine_name.as_deref().unwrap_or("no machine name")
            ),
        ));
    }
    Ok(status)
}

fn resource_memory_mb(value: &str) -> Option<f64> {
    let value = value.trim().to_ascii_lowercase();
    let suffix_start = value.find(|character: char| character.is_ascii_alphabetic())?;
    let (amount, suffix) = value.split_at(suffix_start);
    let amount: f64 = amount.trim().parse().ok()?;
    let multiplier = match suffix.trim_end_matches('b').trim_end_matches('i') {
        "k" => 1.0 / 1024.0,
        "m" => 1.0,
        "g" => 1024.0,
        "t" => 1024.0 * 1024.0,
        _ => return None,
    };
    let memory = amount * multiplier;
    (memory.is_finite() && memory > 0.0).then_some(memory)
}

fn parse_instance_status(raw: &str) -> BridgeResult<InstanceStatus> {
    let status: InstanceStatus = serde_json::from_str(raw).map_err(|_| {
        cli_error(raw).unwrap_or_else(|| {
            BridgeError::new(
                "INVALID_INSTANCE_JSON",
                "The bundled CLI returned an invalid environment status.",
            )
        })
    })?;
    if status.container != platform::resource_name(CONTAINER_NAME)
        || status.image.is_empty()
        || status.web_ui_port.parse::<u16>().is_err()
    {
        return Err(BridgeError::new(
            "INVALID_INSTANCE_JSON",
            "The bundled CLI returned an invalid environment status.",
        ));
    }
    Ok(status)
}

fn cli_error(raw: &str) -> Option<BridgeError> {
    raw.lines()
        .filter_map(|line| serde_json::from_str::<serde_json::Value>(line).ok())
        .find_map(|value| {
            let error = value.get("error")?;
            let mut bridge_error = BridgeError::new(
                error
                    .get("code")
                    .and_then(|value| value.as_str())
                    .unwrap_or("CLI_FAILED"),
                error
                    .get("message")
                    .and_then(|value| value.as_str())
                    .unwrap_or("The bundled CLI command failed."),
            );
            bridge_error.stage = value
                .get("stage")
                .and_then(|value| value.as_str())
                .map(str::to_owned);
            if let Some(detail) = error.get("detail").and_then(|value| value.as_str()) {
                bridge_error = bridge_error.with_stderr(detail.to_owned());
            }
            Some(bridge_error)
        })
}

fn require_success(result: ProcessResult, label: &str) -> BridgeResult<ProcessResult> {
    if result.exit_code == 0 {
        return Ok(result);
    }
    if let Some(error) = cli_error(&result.stdout).or_else(|| cli_error(&result.stderr)) {
        return Err(error.with_stderr(result.stderr));
    }
    Err(BridgeError::new(
        "CLI_EXITED_NONZERO",
        format!("{label} exited with code {}.", result.exit_code),
    )
    .with_stderr(result.stderr))
}

async fn validate_bundled_cli(app: &AppHandle) -> BridgeResult<()> {
    let result = require_success(
        run_fixed(app, FixedOperation::Version).await?,
        "CLI version inspection",
    )?;
    parse_cli_version(&result.stdout)?;
    Ok(())
}

async fn runtime_status(app: &AppHandle) -> BridgeResult<RuntimeStatus> {
    let result = run_fixed(app, FixedOperation::RuntimeStatus).await?;
    // Structured status is authoritative even when an older CLI reports a
    // stopped runtime with a nonzero exit status.
    parse_runtime_status(&result.stdout).map_err(|parse_error| {
        if result.exit_code != 0 {
            cli_error(&result.stdout)
                .or_else(|| cli_error(&result.stderr))
                .unwrap_or(parse_error)
                .with_stderr(result.stderr)
        } else {
            parse_error
        }
    })
}

async fn instance_status(app: &AppHandle) -> BridgeResult<InstanceStatus> {
    let result = run_fixed(app, FixedOperation::InstanceStatus).await?;
    parse_instance_status(&result.stdout).map_err(|parse_error| {
        if result.exit_code != 0 {
            cli_error(&result.stdout)
                .or_else(|| cli_error(&result.stderr))
                .unwrap_or(parse_error)
                .with_stderr(result.stderr)
        } else {
            parse_error
        }
    })
}

fn read_setup_record() -> Option<SetupRecord> {
    let path = platform::user_data_dir().ok()?.join("setup-state.json");
    let record: SetupRecord = serde_json::from_slice(&fs::read(path).ok()?).ok()?;
    if record.schema_version != 2
        || !matches!(record.status.as_str(), "in-progress" | "complete")
        || !matches!(
            record.reason.as_str(),
            "first-run" | "resume" | "update" | "repair"
        )
        || record.app_version.is_empty()
        || record.image_version.is_empty()
        || record.image_ref.is_empty()
    {
        return None;
    }
    Some(record)
}

fn persisted_port() -> Option<u16> {
    let raw = fs::read_to_string(platform::user_data_dir().ok()?.join("runtime/app-port")).ok()?;
    raw.trim().parse().ok().filter(|port| *port > 0)
}

fn reserve_and_persist_port(force_new: bool) -> BridgeResult<u16> {
    if !force_new {
        if let Some(port) = persisted_port() {
            return Ok(port);
        }
    }
    let listener = TcpListener::bind(("127.0.0.1", DEFAULT_APP_PORT))
        .or_else(|_| TcpListener::bind(("127.0.0.1", 0)))
        .map_err(|error| BridgeError::new("PORT_UNAVAILABLE", error.to_string()))?;
    let port = listener
        .local_addr()
        .map_err(|error| BridgeError::new("PORT_UNAVAILABLE", error.to_string()))?
        .port();
    drop(listener);
    let path = platform::user_data_dir()?.join("runtime/app-port");
    fs::create_dir_all(path.parent().expect("runtime has a parent"))
        .map_err(|error| BridgeError::new("STATE_WRITE_FAILED", error.to_string()))?;
    fs::write(path, format!("{port}\n"))
        .map_err(|error| BridgeError::new("STATE_WRITE_FAILED", error.to_string()))?;
    Ok(port)
}

fn image_manifest() -> BridgeResult<ImageManifest> {
    let manifest: ImageManifest =
        serde_json::from_str(include_str!("../resources/image-manifest.json"))
            .map_err(|error| BridgeError::new("INVALID_IMAGE_MANIFEST", error.to_string()))?;
    let valid_ref = manifest.image_ref.starts_with("ghcr.io/")
        && manifest.image_ref.contains("@sha256:")
        && manifest
            .image_ref
            .rsplit("@sha256:")
            .next()
            .is_some_and(|digest| {
                digest.len() == 64 && digest.bytes().all(|byte| byte.is_ascii_hexdigit())
            });
    if manifest.schema_version != 3
        || manifest.app_version != APP_VERSION
        || manifest.image_version.is_empty()
        || !valid_ref
    {
        return Err(BridgeError::new(
            "INVALID_IMAGE_MANIFEST",
            "The omnideck runtime image does not match this application release.",
        ));
    }
    Ok(manifest)
}

fn save_setup_record(status: &str, reason: &str, manifest: &ImageManifest) -> BridgeResult<()> {
    let digest = manifest.image_ref.rsplit('@').next().unwrap_or("");
    let record = SetupRecordWrite {
        schema_version: 2,
        status,
        reason,
        app_version: APP_VERSION,
        image_version: &manifest.image_version,
        image_ref: &manifest.image_ref,
        image_digest: digest,
        updated_at: time::OffsetDateTime::now_utc()
            .format(&time::format_description::well_known::Rfc3339)
            .map_err(|error| BridgeError::new("STATE_WRITE_FAILED", error.to_string()))?,
    };
    let destination = platform::user_data_dir()?.join("setup-state.json");
    fs::create_dir_all(destination.parent().expect("state has a parent"))
        .map_err(|error| BridgeError::new("STATE_WRITE_FAILED", error.to_string()))?;
    let temporary = destination.with_extension(format!("{}.partial", std::process::id()));
    let mut encoded = serde_json::to_vec_pretty(&record)
        .map_err(|error| BridgeError::new("STATE_WRITE_FAILED", error.to_string()))?;
    encoded.push(b'\n');
    fs::write(&temporary, encoded)
        .map_err(|error| BridgeError::new("STATE_WRITE_FAILED", error.to_string()))?;
    if destination.exists() {
        fs::remove_file(&destination)
            .map_err(|error| BridgeError::new("STATE_WRITE_FAILED", error.to_string()))?;
    }
    fs::rename(temporary, destination)
        .map_err(|error| BridgeError::new("STATE_WRITE_FAILED", error.to_string()))
}

fn resource_string(status: &RuntimeStatus, key: &str, fallback: &str) -> String {
    match key {
        "memory" => status.resources.container.memory.clone(),
        "shmSize" => status.resources.container.shm_size.clone(),
        _ => fallback.to_owned(),
    }
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
        .inner_size(1280.0, 820.0)
        .min_inner_size(880.0, 620.0)
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
    .enable_clipboard_access()
    .initialization_script(HOSTED_SHORTCUTS_SCRIPT)
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
        if record.app_version != APP_VERSION
            || record.image_version != manifest.image_version
            || record.image_ref != manifest.image_ref
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
            || status.image != manifest.image_ref
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
        let manifest = image_manifest()?;
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
                    if let Ok(event) = serde_json::from_str::<serde_json::Value>(line) {
                        if let Some(state) =
                            setup_state_from_cli_event(&reason_for_events, &event, &mut last_step)
                        {
                            if let Some(phase) = event
                                .get("stage")
                                .and_then(|value| value.as_str())
                                .and_then(parity::phase_index)
                            {
                                reached_phase_for_events.fetch_max(phase, Ordering::AcqRel);
                            }
                            let _ = channel.send(state);
                        }
                    }
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
        let memory = resource_string(&runtime, "memory", "2g");
        let shm_size = resource_string(&runtime, "shmSize", "1g");
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
                if let Ok(event) = serde_json::from_str::<serde_json::Value>(line) {
                    if let Some(state) =
                        setup_state_from_cli_event(&reason_for_events, &event, &mut last_step)
                    {
                        if let Some(phase) = event
                            .get("stage")
                            .and_then(|value| value.as_str())
                            .and_then(|stage| {
                                if stage == "pull_image" {
                                    parity::phase_index("download")
                                } else {
                                    parity::phase_index("startup")
                                }
                            })
                        {
                            reached_phase_for_events.fetch_max(phase, Ordering::AcqRel);
                        }
                        let _ = channel.send(state);
                    }
                }
            })
            .await?;
            match require_success(environment, "Reconcile application environment") {
                Ok(_) => break,
                Err(error) if error.code == "PORT_IN_USE" && attempt == 0 => {
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
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            bootstrap,
            begin_setup,
            open_app,
            run_action
        ])
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::CloseRequested { .. }) {
                // Both webviews are created up front and one is always hidden. Exiting
                // here prevents that hidden companion from leaving a headless process.
                window.app_handle().exit(0);
            }
        })
        .setup(move |app| {
            #[cfg(target_os = "macos")]
            app.set_menu(tauri::menu::Menu::default(app.handle())?)?;
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
    fn operation_arguments_are_fixed() {
        assert_eq!(FixedOperation::Version.args(), ["--version"]);
        assert_eq!(
            FixedOperation::RuntimeStatus.args(),
            ["--json", "runtime", "status"]
        );
        assert_eq!(
            FixedOperation::InstanceStatus.args(),
            ["--json", "--name", CONTAINER_NAME, "status"]
        );
        assert_eq!(
            FixedOperation::StartInstance.args(),
            ["--json", "--name", CONTAINER_NAME, "start"]
        );
    }

    #[test]
    fn validates_the_immutable_cli_version() {
        let parsed = parse_cli_version(
            "omnideck version v0.11.0-alpha.1 (48434a5f82c0) built 2026-08-09T16:47:13Z",
        )
        .unwrap();
        assert_eq!(parsed.version, EXPECTED_CLI_VERSION);
        assert_eq!(parsed.commit, EXPECTED_CLI_COMMIT);
        assert!(parse_cli_version("omnideck version v9.9.9 (deadbee)").is_err());
    }

    #[test]
    fn validates_schema_four_podman_status() {
        assert!(
            parse_runtime_status(
                r#"{"schemaVersion":4,"runtime":"podman","state":"ready","ready":true,"machineName":"omnideck-runtime","resources":{"container":{"memory":"4g","shmSize":"2g"},"machine":{"mode":"wsl-managed"}}}"#
            )
            .unwrap()
            .ready
        );
        assert!(parse_runtime_status(
            r#"{"schemaVersion":5,"runtime":"podman","state":"ready","ready":true,"resources":{"container":{"memory":"4g","shmSize":"2g"},"machine":{"mode":"wsl-managed"}}}"#
        )
        .is_err());
        assert!(parse_runtime_status(
            r#"{"schemaVersion":4,"runtime":"docker","state":"ready","ready":true,"resources":{"container":{"memory":"4g","shmSize":"2g"},"machine":{"mode":"wsl-managed"}}}"#
        )
        .is_err());
        assert!(parse_runtime_status(
            r#"{"schemaVersion":4,"runtime":"podman","state":"ready","ready":true,"machineName":"omnideck-runtime","resources":{"container":{"memory":"1g","shmSize":"2g"},"machine":{"mode":"wsl-managed"}}}"#
        )
        .is_err());
    }

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
    fn output_is_bounded() {
        let mut output = Vec::new();
        append_bounded(&mut output, &[b'a'; 4], 5, "stdout").unwrap();
        append_bounded(&mut output, b"b", 5, "stdout").unwrap();
        assert!(append_bounded(&mut output, b"c", 5, "stdout").is_err());
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
    fn json_lines_are_reassembled_across_process_chunks() {
        let mut buffer = LineBuffer::default();
        let mut lines = Vec::new();
        buffer.push(br#"{"stage":"pull"#, &mut |line| {
            lines.push(line.to_owned())
        });
        buffer.push(b"_image\"}\r\n{\"stage\":\"start", &mut |line| {
            lines.push(line.to_owned())
        });
        buffer.push(b"_container\"}", &mut |line| lines.push(line.to_owned()));
        buffer.flush(&mut |line| lines.push(line.to_owned()));
        assert_eq!(
            lines,
            [
                r#"{"stage":"pull_image"}"#,
                r#"{"stage":"start_container"}"#
            ]
        );
    }
}

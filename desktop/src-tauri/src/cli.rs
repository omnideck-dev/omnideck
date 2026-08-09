use crate::{platform, BridgeError, BridgeResult, CONTAINER_NAME};
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tauri::AppHandle;
use tauri_plugin_shell::{process::CommandEvent, ShellExt};

const EXPECTED_SCHEMA_VERSION: u32 = 4;
pub(crate) const EXPECTED_CLI_VERSION: &str = "v0.11.0-alpha.1";
pub(crate) const EXPECTED_CLI_COMMIT: &str = "48434a5f82c0";
const STDOUT_LIMIT: usize = 1_000_000;
const STDERR_LIMIT: usize = 256 * 1024;
const INSPECTION_TIMEOUT: Duration = Duration::from_secs(15);
pub(crate) const SETUP_TIMEOUT: Duration = Duration::from_secs(20 * 60);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum FixedOperation {
    Version,
    RuntimeStatus,
    RuntimeEnsure,
    InstanceStatus,
    StartInstance,
}

impl FixedOperation {
    pub(crate) fn args(self) -> Vec<String> {
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
pub(crate) struct ProcessResult {
    pub(crate) exit_code: i32,
    pub(crate) stdout: String,
    pub(crate) stderr: String,
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
pub(crate) struct RuntimeStatus {
    pub(crate) schema_version: u32,
    pub(crate) runtime: String,
    pub(crate) state: String,
    pub(crate) ready: bool,
    path: Option<String>,
    version: Option<String>,
    pub(crate) machine_name: Option<String>,
    phase: Option<String>,
    activity: Option<String>,
    pub(crate) resources: RuntimeResources,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct RuntimeResources {
    pub(crate) container: ContainerResources,
    machine: MachineResources,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ContainerResources {
    pub(crate) memory: String,
    pub(crate) shm_size: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct MachineResources {
    mode: String,
    memory_mb: Option<f64>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct InstanceStatus {
    container: String,
    pub(crate) status: String,
    pub(crate) image: String,
    pub(crate) web_ui_port: String,
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

pub(crate) async fn run_cli<F>(
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

pub(crate) async fn run_fixed(
    app: &AppHandle,
    operation: FixedOperation,
) -> BridgeResult<ProcessResult> {
    run_cli(app, operation.args(), operation.timeout(), |_| {}).await
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

pub(crate) fn parse_instance_status(raw: &str) -> BridgeResult<InstanceStatus> {
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

pub(crate) fn require_success(result: ProcessResult, label: &str) -> BridgeResult<ProcessResult> {
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

pub(crate) async fn validate_bundled_cli(app: &AppHandle) -> BridgeResult<()> {
    let result = require_success(
        run_fixed(app, FixedOperation::Version).await?,
        "CLI version inspection",
    )?;
    parse_cli_version(&result.stdout)?;
    Ok(())
}

pub(crate) async fn runtime_status(app: &AppHandle) -> BridgeResult<RuntimeStatus> {
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

pub(crate) async fn instance_status(app: &AppHandle) -> BridgeResult<InstanceStatus> {
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
    fn output_is_bounded() {
        let mut output = Vec::new();
        append_bounded(&mut output, &[b'a'; 4], 5, "stdout").unwrap();
        append_bounded(&mut output, b"b", 5, "stdout").unwrap();
        assert!(append_bounded(&mut output, b"c", 5, "stdout").is_err());
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

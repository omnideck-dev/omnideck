use crate::{lifecycle::Lifecycle, platform, BridgeError, BridgeResult, CONTAINER_NAME};
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tauri::{AppHandle, Manager};
use tauri_plugin_shell::ShellExt;
use tokio::io::AsyncReadExt;

const EXPECTED_SCHEMA_VERSION: u32 = 4;
pub(crate) const EXPECTED_CLI_VERSION: &str = "v0.11.0-beta.6";
pub(crate) const EXPECTED_CLI_COMMIT: &str = "4e2b4e4b23c2";
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

#[derive(Default)]
struct ProcessOutput {
    exit_code: Option<i32>,
    stdout: Vec<u8>,
    stderr: Vec<u8>,
}

impl ProcessOutput {
    fn push_stdout(&mut self, chunk: &[u8]) -> BridgeResult<()> {
        append_bounded(&mut self.stdout, chunk, STDOUT_LIMIT, "stdout")
    }

    fn push_stderr(&mut self, chunk: &[u8]) -> BridgeResult<()> {
        append_bounded(&mut self.stderr, chunk, STDERR_LIMIT, "stderr")
    }

    fn terminate(&mut self, exit_code: i32) -> BridgeResult<()> {
        if self.exit_code.replace(exit_code).is_some() {
            return Err(BridgeError::new(
                "SIDECAR_IO_FAILED",
                "The bundled CLI reported process termination more than once.",
            ));
        }
        Ok(())
    }

    fn finish(self) -> BridgeResult<ProcessResult> {
        let exit_code = self.exit_code.ok_or_else(|| {
            BridgeError::new(
                "SIDECAR_IO_FAILED",
                "The bundled CLI event stream ended before process termination.",
            )
        })?;
        Ok(ProcessResult {
            exit_code,
            stdout: String::from_utf8_lossy(&self.stdout).trim().to_owned(),
            stderr: String::from_utf8_lossy(&self.stderr).trim().to_owned(),
        })
    }
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
    #[serde(rename = "memoryMB")]
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
    run_process(
        &app.state::<Lifecycle>(),
        command.into(),
        timeout_duration,
        &mut on_stdout,
    )
    .await
}

async fn run_process<F>(
    lifecycle: &Lifecycle,
    mut command: std::process::Command,
    timeout_duration: Duration,
    mut on_stdout: F,
) -> BridgeResult<ProcessResult>
where
    F: FnMut(&str),
{
    command
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());
    let (mut child, mut operation) = lifecycle
        .spawn(command)
        .map_err(|error| BridgeError::new("SIDECAR_SPAWN_FAILED", error.to_string()))?;
    let mut stdout = child.stdout.take().expect("stdout is piped");
    let mut stderr = child.stderr.take().expect("stderr is piped");
    let mut stdout_buffer = [0u8; 8192];
    let mut stderr_buffer = [0u8; 8192];
    let mut stdout_done = false;
    let mut stderr_done = false;
    let mut output = ProcessOutput::default();
    let mut stdout_lines = LineBuffer::default();
    let mut timeout = Box::pin(tokio::time::sleep(timeout_duration));

    loop {
        if stdout_done && stderr_done && output.exit_code.is_some() {
            operation.complete();
            stdout_lines.flush(&mut on_stdout);
            return output.finish();
        }
        let error = tokio::select! {
            _ = operation.cancelled() => {
                Some(BridgeError::new("SIDECAR_CANCELLED", "omnideck is closing."))
            }
            _ = &mut timeout => {
                Some(BridgeError::new("SIDECAR_TIMEOUT", "The bundled CLI did not finish in time."))
            }
            read = stdout.read(&mut stdout_buffer), if !stdout_done => match read {
                Ok(0) => { stdout_done = true; None }
                Ok(read) => {
                    if let Err(error) = output.push_stdout(&stdout_buffer[..read]) {
                        Some(error)
                    } else {
                        stdout_lines.push(&stdout_buffer[..read], &mut on_stdout);
                        None
                    }
                }
                Err(error) => Some(BridgeError::new("SIDECAR_IO_FAILED", error.to_string())),
            },
            read = stderr.read(&mut stderr_buffer), if !stderr_done => match read {
                Ok(0) => { stderr_done = true; None }
                Ok(read) => output.push_stderr(&stderr_buffer[..read]).err(),
                Err(error) => Some(BridgeError::new("SIDECAR_IO_FAILED", error.to_string())),
            },
            status = child.wait(), if output.exit_code.is_none() => match status {
                Ok(status) => {
                    // Drain both pipes after exit so final JSON is not lost.
                    output.terminate(status.code().unwrap_or(-1)).err()
                }
                Err(error) => Some(BridgeError::new("SIDECAR_IO_FAILED", error.to_string())),
            },
        };
        if let Some(error) = error {
            operation.stop(&mut child).await;
            return Err(error);
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
            "omnideck version v0.11.0-beta.6 (4e2b4e4b23c2) built 2026-09-29T01:48:47Z",
        )
        .unwrap();
        assert_eq!(parsed.version, EXPECTED_CLI_VERSION);
        assert_eq!(parsed.commit, EXPECTED_CLI_COMMIT);
        assert!(parse_cli_version("omnideck version v9.9.9 (deadbee)").is_err());
    }

    #[test]
    fn collects_output_that_arrives_after_process_termination() {
        let mut output = ProcessOutput::default();
        output.terminate(0).unwrap();
        output.push_stdout(b"late stdout").unwrap();
        output.push_stderr(b"late stderr").unwrap();

        let result = output.finish().unwrap();
        assert_eq!(result.exit_code, 0);
        assert_eq!(result.stdout, "late stdout");
        assert_eq!(result.stderr, "late stderr");
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
    fn accepts_the_cli_memory_mb_wire_field_on_macos() {
        let status = parse_runtime_status(
            r#"{"schemaVersion":4,"runtime":"podman","state":"machine_missing","ready":false,"resources":{"container":{"memory":"4g","shmSize":"2g"},"machine":{"mode":"podman-managed","memoryMB":8192}}}"#,
        )
        .unwrap();
        assert_eq!(status.resources.machine.memory_mb, Some(8192.0));

        let error = parse_runtime_status(
            r#"{"schemaVersion":4,"runtime":"podman","state":"machine_missing","ready":false,"resources":{"container":{"memory":"4g","shmSize":"2g"},"machine":{"mode":"podman-managed","memoryMb":8192}}}"#,
        )
        .unwrap_err();
        assert_eq!(error.code, "INVALID_RUNTIME_RESOURCES");
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

    #[cfg(unix)]
    #[tokio::test]
    async fn process_pipes_deliver_progress_and_final_output() {
        let mut command = std::process::Command::new("sh");
        command.args(["-c", "printf '{\"stage\":\"start\"}\\n'; printf diagnostic >&2; printf '{\"stage\":\"done\"}\\n'"]);
        let mut lines = Vec::new();
        let result = run_process(
            &Lifecycle::default(),
            command,
            Duration::from_secs(5),
            |line| lines.push(line.to_owned()),
        )
        .await
        .unwrap();
        assert_eq!(result.exit_code, 0);
        assert_eq!(result.stderr, "diagnostic");
        assert_eq!(lines, [r#"{"stage":"start"}"#, r#"{"stage":"done"}"#]);
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn process_timeout_cancels_the_command() {
        let mut command = std::process::Command::new("sh");
        command.args(["-c", "sleep 60"]);
        let lifecycle = Lifecycle::default();
        let error = run_process(&lifecycle, command, Duration::from_millis(30), |_| {})
            .await
            .unwrap_err();
        assert_eq!(error.code, "SIDECAR_TIMEOUT");
        assert!(lifecycle.begin_shutdown());
        tokio::time::timeout(Duration::from_secs(1), lifecycle.shutdown())
            .await
            .unwrap();
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn unbroken_output_is_limited_before_a_newline_arrives() {
        let mut command = std::process::Command::new("sh");
        command.args(["-c", "head -c 1000001 /dev/zero; sleep 60"]);
        let error = run_process(
            &Lifecycle::default(),
            command,
            Duration::from_secs(5),
            |_| {},
        )
        .await
        .unwrap_err();
        assert_eq!(error.code, "OUTPUT_LIMIT");
    }
}

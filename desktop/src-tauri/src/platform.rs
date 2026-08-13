use crate::{BridgeError, BridgeResult};
use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

#[cfg(target_os = "windows")]
pub const KEY: &str = "win32";
#[cfg(target_os = "macos")]
pub const KEY: &str = "darwin";
#[cfg(target_os = "linux")]
pub const KEY: &str = "linux";

#[cfg(not(any(target_os = "windows", target_os = "macos", target_os = "linux")))]
compile_error!("omnideck desktop supports Windows, macOS, and Linux only");

pub fn uses_managed_machine() -> bool {
    cfg!(any(target_os = "windows", target_os = "macos"))
}

fn test_namespace() -> Option<String> {
    let namespace = std::env::var("OMNIDECK_DESKTOP_TEST_NAMESPACE").ok()?;
    (!namespace.is_empty()
        && namespace.len() <= 40
        && namespace
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-'))
    .then_some(namespace)
}

pub fn is_test_run() -> bool {
    test_namespace().is_some()
}

pub fn resource_name(base: &str) -> String {
    test_namespace()
        .map(|namespace| format!("{base}-{namespace}"))
        .unwrap_or_else(|| base.to_owned())
}

pub fn machine_name() -> String {
    test_namespace()
        .map(|namespace| format!("odrt-{namespace}"))
        .unwrap_or_else(|| "omnideck-runtime".to_owned())
}

pub fn user_data_dir() -> BridgeResult<PathBuf> {
    if let Some(path) = std::env::var_os("OMNIDECK_DESKTOP_USER_DATA") {
        return Ok(PathBuf::from(path));
    }
    #[cfg(target_os = "windows")]
    let root = std::env::var_os("APPDATA").map(PathBuf::from);
    #[cfg(target_os = "macos")]
    let root = std::env::var_os("HOME")
        .map(|home| PathBuf::from(home).join("Library/Application Support"));
    #[cfg(target_os = "linux")]
    let root = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".config")));

    root.map(|root| root.join("omnideck")).ok_or_else(|| {
        BridgeError::new(
            "USER_DATA_UNAVAILABLE",
            "The omnideck user-data directory could not be resolved.",
        )
    })
}

pub fn diagnostic_log() -> BridgeResult<PathBuf> {
    Ok(user_data_dir()?.join("logs/desktop.log"))
}

pub fn append_diagnostic(message: &str) {
    let Ok(path) = diagnostic_log() else {
        return;
    };
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(file, "{message}");
    }
}

fn command(program: impl AsRef<Path>) -> Command {
    let mut command = Command::new(program.as_ref());
    command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    command
}

fn spawn(program: &str, args: &[String]) -> BridgeResult<()> {
    command(program)
        .args(args)
        .spawn()
        .map(|_| ())
        .map_err(|error| BridgeError::new("ACTION_FAILED", error.to_string()))
}

pub fn open_url(url: &str) -> BridgeResult<()> {
    #[cfg(target_os = "windows")]
    return spawn(
        "rundll32.exe",
        &["url.dll,FileProtocolHandler".into(), url.into()],
    );
    #[cfg(target_os = "macos")]
    return spawn("open", &[url.into()]);
    #[cfg(target_os = "linux")]
    return spawn("xdg-open", &[url.into()]);
}

#[cfg(target_os = "windows")]
fn windows_tool(name: &str) -> PathBuf {
    std::env::var_os("SystemRoot")
        .or_else(|| std::env::var_os("WINDIR"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(r"C:\Windows"))
        .join("System32")
        .join(name)
}

#[cfg(target_os = "windows")]
fn run_and_wait(program: &Path, args: &[String]) -> BridgeResult<()> {
    let status = command(program)
        .args(args)
        .status()
        .map_err(|error| BridgeError::new("ACTION_FAILED", error.to_string()))?;
    if status.success() {
        Ok(())
    } else {
        Err(BridgeError::new(
            "ACTION_FAILED",
            format!("{} exited with {status}.", program.display()),
        ))
    }
}

#[cfg(target_os = "windows")]
pub fn restart_computer() -> BridgeResult<()> {
    const RUN_ONCE_KEY: &str = r"HKCU\Software\Microsoft\Windows\CurrentVersion\RunOnce";
    let executable = std::env::current_exe()
        .map_err(|error| BridgeError::new("ACTION_FAILED", error.to_string()))?;
    let resume_value = format!("\"{}\"", executable.display());
    let register = vec![
        "add".into(),
        RUN_ONCE_KEY.into(),
        "/v".into(),
        "omnideckSetupResume".into(),
        "/t".into(),
        "REG_SZ".into(),
        "/d".into(),
        resume_value,
        "/f".into(),
    ];
    run_and_wait(&windows_tool("reg.exe"), &register)?;

    let restart = command(windows_tool("shutdown.exe"))
        .args(["/r", "/t", "0"])
        .spawn();
    if let Err(error) = restart {
        let cancel = vec![
            "delete".into(),
            RUN_ONCE_KEY.into(),
            "/v".into(),
            "omnideckSetupResume".into(),
            "/f".into(),
        ];
        let _ = run_and_wait(&windows_tool("reg.exe"), &cancel);
        return Err(BridgeError::new("ACTION_FAILED", error.to_string()));
    }
    Ok(())
}

#[cfg(not(target_os = "windows"))]
pub fn restart_computer() -> BridgeResult<()> {
    Err(BridgeError::new(
        "ACTION_UNAVAILABLE",
        "Restarting from omnideck is only supported on Windows.",
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn platform_key_matches_the_electron_contract() {
        assert!(["win32", "darwin", "linux"].contains(&KEY));
    }

    #[test]
    fn managed_machine_policy_matches_podman_hosts() {
        assert_eq!(
            uses_managed_machine(),
            cfg!(any(target_os = "windows", target_os = "macos"))
        );
    }

    #[test]
    fn production_resource_names_are_stable() {
        if std::env::var_os("OMNIDECK_DESKTOP_TEST_NAMESPACE").is_none() {
            assert_eq!(resource_name("omnideck-desktop"), "omnideck-desktop");
            assert_eq!(machine_name(), "omnideck-runtime");
        }
    }
}

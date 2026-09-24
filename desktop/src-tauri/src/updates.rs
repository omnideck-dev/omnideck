use crate::{
    navigation::{authorize_hosted, is_hosted_app_url},
    platform,
    runtime::{BridgeError, BridgeResult, HostState},
    state, windows,
};
use reqwest::header::{ACCEPT, AUTHORIZATION};
use serde::{Deserialize, Serialize};
use std::{fs, sync::atomic::Ordering, time::Duration};
use tauri::{AppHandle, Manager, WebviewWindow};
use tauri_plugin_notification::NotificationExt;

const UPDATE_STATE_SCHEMA: u32 = 1;
const REPOSITORY: &str = "omnideck-dev/omnideck";
const REGISTRY: &str = "https://ghcr.io";
const MANIFEST_TYPES: &str = "application/vnd.oci.image.index.v1+json,application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.docker.distribution.manifest.v2+json";
const FIRST_CHECK: Duration = Duration::from_secs(10);
const CHECK_INTERVAL: Duration = Duration::from_secs(6 * 60 * 60);

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct UpdateTarget {
    pub(crate) version: String,
    pub(crate) image_ref: String,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub(crate) struct UpdatePayload {
    pub(crate) version: String,
    pub(crate) deferred: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct UpdateState {
    schema_version: u32,
    pub(crate) skipped_version: Option<String>,
    pub(crate) deferred_version: Option<String>,
    #[serde(default = "enabled")]
    pub(crate) automatic: bool,
    #[serde(default = "enabled")]
    pub(crate) notify: bool,
    checked_at: Option<String>,
    pub(crate) version: Option<String>,
    pub(crate) image_ref: Option<String>,
}

fn enabled() -> bool {
    true
}

impl Default for UpdateState {
    fn default() -> Self {
        Self {
            schema_version: UPDATE_STATE_SCHEMA,
            skipped_version: None,
            deferred_version: None,
            automatic: true,
            notify: true,
            checked_at: None,
            version: None,
            image_ref: None,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
struct Version(u64, u64, u64);

fn parse_release(value: &str) -> Option<Version> {
    let mut parts = value.trim().split('.');
    let version = Version(
        parts.next()?.parse().ok()?,
        parts.next()?.parse().ok()?,
        parts.next()?.parse().ok()?,
    );
    parts.next().is_none().then_some(version)
}

pub(crate) fn is_newer_release(candidate: &str, installed: &str) -> bool {
    matches!(
        (parse_release(candidate), parse_release(installed)),
        (Some(candidate), Some(installed)) if candidate > installed
    )
}

fn valid_image_ref(value: &str) -> bool {
    let Some((repository, digest)) = value.rsplit_once("@sha256:") else {
        return false;
    };
    repository.starts_with("ghcr.io/")
        && digest.len() == 64
        && digest.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn select_version<'a>(
    tags: impl IntoIterator<Item = &'a str>,
    installed: &str,
    skipped: Option<&str>,
) -> Option<String> {
    let installed = parse_release(installed)?;
    let skipped = skipped
        .and_then(parse_release)
        .filter(|value| *value > installed);
    tags.into_iter()
        .filter_map(|tag| parse_release(tag).map(|version| (tag, version)))
        .filter(|(_, version)| *version > installed && skipped.is_none_or(|floor| *version > floor))
        .max_by_key(|(_, version)| *version)
        .map(|(tag, _)| tag.to_owned())
}

fn update_state_path() -> BridgeResult<std::path::PathBuf> {
    Ok(platform::user_data_dir()?.join("update-state.json"))
}

pub(crate) fn read_state() -> UpdateState {
    let Ok(path) = update_state_path() else {
        return UpdateState::default();
    };
    let Ok(value) = fs::read(&path)
        .ok()
        .and_then(|bytes| serde_json::from_slice::<UpdateState>(&bytes).ok())
        .ok_or(())
    else {
        return UpdateState::default();
    };
    if value.schema_version != UPDATE_STATE_SCHEMA
        || value
            .version
            .as_deref()
            .is_some_and(|version| parse_release(version).is_none())
        || value
            .image_ref
            .as_deref()
            .is_some_and(|image| !valid_image_ref(image))
    {
        return UpdateState::default();
    }
    value
}

fn write_state(value: &UpdateState) -> BridgeResult<()> {
    let mut encoded = serde_json::to_vec_pretty(value)
        .map_err(|error| BridgeError::new("UPDATE_STATE_FAILED", error.to_string()))?;
    encoded.push(b'\n');
    state::write_atomic(&update_state_path()?, &encoded)
}

fn target_from_state(value: &UpdateState) -> Option<UpdateTarget> {
    Some(UpdateTarget {
        version: value.version.clone()?,
        image_ref: value.image_ref.clone()?,
    })
}

pub(crate) fn known_update(installed: &str) -> Option<UpdateTarget> {
    let state = read_state();
    let target = target_from_state(&state)?;
    select_version(
        std::iter::once(target.version.as_str()),
        installed,
        state.skipped_version.as_deref(),
    )?;
    Some(target)
}

pub(crate) fn pending_at_launch(installed: &str) -> Option<UpdateTarget> {
    let state = read_state();
    let target = known_update(installed)?;
    (state.automatic || state.deferred_version.as_deref() == Some(target.version.as_str()))
        .then_some(target)
}

fn fixture_update(installed: &str, skipped: Option<&str>) -> BridgeResult<Option<UpdateTarget>> {
    if !platform::is_test_run() {
        return Ok(None);
    }
    let Some(path) = std::env::var_os("OMNIDECK_DESKTOP_UPDATE_FIXTURE") else {
        return Ok(None);
    };
    let target: UpdateTarget = serde_json::from_slice(
        &fs::read(path)
            .map_err(|error| BridgeError::new("UPDATE_FIXTURE_FAILED", error.to_string()))?,
    )
    .map_err(|error| BridgeError::new("UPDATE_FIXTURE_FAILED", error.to_string()))?;
    if !valid_image_ref(&target.image_ref) || parse_release(&target.version).is_none() {
        return Err(BridgeError::new(
            "UPDATE_FIXTURE_FAILED",
            "The update fixture is invalid.",
        ));
    }
    Ok(
        select_version(std::iter::once(target.version.as_str()), installed, skipped)
            .map(|_| target),
    )
}

async fn registry_update(
    installed: &str,
    skipped: Option<&str>,
) -> BridgeResult<Option<UpdateTarget>> {
    if platform::is_test_run() && std::env::var_os("OMNIDECK_DESKTOP_UPDATE_FIXTURE").is_some() {
        return fixture_update(installed, skipped);
    }
    let client = reqwest::Client::builder()
        .user_agent(format!("omnideck-desktop/{}", state::APP_VERSION))
        .timeout(std::time::Duration::from_secs(20))
        .build()
        .map_err(|error| BridgeError::new("UPDATE_CHECK_FAILED", error.to_string()))?;
    let token_url = format!(
        "{REGISTRY}/token?scope={}&service=ghcr.io",
        "repository%3Aomnideck-dev%2Fomnideck%3Apull"
    );
    let token_value: serde_json::Value = client
        .get(token_url)
        .send()
        .await
        .and_then(reqwest::Response::error_for_status)
        .map_err(|error| BridgeError::new("UPDATE_CHECK_FAILED", error.to_string()))?
        .json()
        .await
        .map_err(|error| BridgeError::new("UPDATE_CHECK_FAILED", error.to_string()))?;
    let token = token_value
        .get("token")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| {
            BridgeError::new(
                "UPDATE_CHECK_FAILED",
                "The registry did not grant read access.",
            )
        })?;
    let tags_value: serde_json::Value = client
        .get(format!("{REGISTRY}/v2/{REPOSITORY}/tags/list?n=1000"))
        .header(AUTHORIZATION, format!("Bearer {token}"))
        .send()
        .await
        .and_then(reqwest::Response::error_for_status)
        .map_err(|error| BridgeError::new("UPDATE_CHECK_FAILED", error.to_string()))?
        .json()
        .await
        .map_err(|error| BridgeError::new("UPDATE_CHECK_FAILED", error.to_string()))?;
    let version = select_version(
        tags_value
            .get("tags")
            .and_then(serde_json::Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(serde_json::Value::as_str),
        installed,
        skipped,
    );
    let Some(version) = version else {
        return Ok(None);
    };
    let response = client
        .head(format!("{REGISTRY}/v2/{REPOSITORY}/manifests/{version}"))
        .header(AUTHORIZATION, format!("Bearer {token}"))
        .header(ACCEPT, MANIFEST_TYPES)
        .send()
        .await
        .and_then(reqwest::Response::error_for_status)
        .map_err(|error| BridgeError::new("UPDATE_CHECK_FAILED", error.to_string()))?;
    let digest = response
        .headers()
        .get("docker-content-digest")
        .and_then(|value| value.to_str().ok())
        .unwrap_or("");
    let image_ref = format!("ghcr.io/{REPOSITORY}@{digest}");
    if !valid_image_ref(&image_ref) {
        return Err(BridgeError::new(
            "UPDATE_CHECK_FAILED",
            "The registry did not identify that release.",
        ));
    }
    Ok(Some(UpdateTarget { version, image_ref }))
}

pub(crate) async fn check(installed: &str) -> BridgeResult<Option<UpdateTarget>> {
    let mut state = read_state();
    let found = registry_update(installed, state.skipped_version.as_deref()).await?;
    state.checked_at = Some(
        time::OffsetDateTime::now_utc()
            .format(&time::format_description::well_known::Rfc3339)
            .map_err(|error| BridgeError::new("UPDATE_STATE_FAILED", error.to_string()))?,
    );
    state.version = found.as_ref().map(|value| value.version.clone());
    state.image_ref = found.as_ref().map(|value| value.image_ref.clone());
    write_state(&state)?;
    Ok(found)
}

pub(crate) fn defer(target: &UpdateTarget) -> BridgeResult<()> {
    let mut state = read_state();
    state.deferred_version = Some(target.version.clone());
    write_state(&state)
}

pub(crate) fn skip(target: &UpdateTarget) -> BridgeResult<()> {
    let mut state = read_state();
    state.skipped_version = Some(target.version.clone());
    state.deferred_version = None;
    state.version = None;
    state.image_ref = None;
    write_state(&state)
}

pub(crate) fn complete() -> BridgeResult<()> {
    let mut state = read_state();
    state.deferred_version = None;
    state.version = None;
    state.image_ref = None;
    write_state(&state)
}

pub(crate) fn set_preferences(automatic: bool, notify: bool) -> BridgeResult<()> {
    let mut state = read_state();
    state.automatic = automatic;
    state.notify = notify;
    write_state(&state)
}

pub(crate) fn payload(target: &UpdateTarget, deferred: Option<&str>) -> UpdatePayload {
    UpdatePayload {
        version: target.version.clone(),
        deferred: deferred == Some(target.version.as_str()),
    }
}

fn publish(app: &AppHandle, host: &HostState) {
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
        .map(|target| payload(target, deferred.as_deref()));
    let Ok(encoded) = serde_json::to_string(&payload) else {
        return;
    };
    if let Some(window) = app.get_webview_window("hosted-app") {
        let _ = window.eval(format!(
            "window.dispatchEvent(new CustomEvent('omnideck:update',{{detail:{encoded}}}));"
        ));
    }
}

#[derive(Deserialize)]
struct SoftwareUpdatePreferences {
    software_updates_automatic: Option<bool>,
    software_updates_notify: Option<bool>,
}

async fn remember_preferences(host: &HostState) -> BridgeResult<()> {
    let port = host
        .hosted_port
        .read()
        .ok()
        .and_then(|value| *value)
        .or_else(state::persisted_port)
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
    set_preferences(
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

async fn perform_check(app: &AppHandle, host: &HostState) -> BridgeResult<Option<UpdateTarget>> {
    let installed = state::read_setup_record()
        .map(|record| record.image_version)
        .unwrap_or_else(|| {
            state::image_manifest()
                .map(|manifest| manifest.image_version)
                .unwrap_or_default()
        });
    if installed.is_empty() {
        return Ok(None);
    }
    let previous = read_state();
    let found = check(&installed).await?;
    if let Ok(mut available) = host.available_update.write() {
        *available = found.clone();
    }
    let persisted = read_state();
    if let Ok(mut deferred) = host.deferred_version.write() {
        *deferred = persisted.deferred_version;
    }
    publish(app, host);
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

pub(crate) fn schedule_update_checks(app: &AppHandle, host: &HostState) {
    if host.update_checks_started.swap(true, Ordering::AcqRel) {
        return;
    }
    let app = app.clone();
    let host = host.clone();
    tauri::async_runtime::spawn(async move {
        tokio::time::sleep(FIRST_CHECK).await;
        loop {
            if let Err(error) = remember_preferences(&host).await {
                platform::append_diagnostic(&format!("[update preferences] {}", error.technical()));
            }
            if let Err(error) = perform_check(&app, &host).await {
                platform::append_diagnostic(&format!("[update check] {}", error.technical()));
            }
            tokio::time::sleep(CHECK_INTERVAL).await;
        }
    });
}

#[tauri::command]
pub(crate) fn current_update(
    window: WebviewWindow,
    host: tauri::State<'_, HostState>,
) -> BridgeResult<Option<UpdatePayload>> {
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
        .map(|target| payload(target, deferred.as_deref())))
}

#[tauri::command]
pub(crate) async fn check_for_update(
    app: AppHandle,
    window: WebviewWindow,
    host: tauri::State<'_, HostState>,
) -> BridgeResult<Option<UpdatePayload>> {
    authorize_hosted(&window, &host)?;
    remember_preferences(&host).await?;
    perform_check(&app, &host).await?;
    current_update(window, host)
}

fn available_update(host: &HostState) -> BridgeResult<UpdateTarget> {
    host.available_update
        .read()
        .map_err(|_| BridgeError::new("STATE_LOCK_FAILED", "The update lock was poisoned."))?
        .clone()
        .ok_or_else(|| BridgeError::new("UPDATE_MISSING", "There is no update to act on."))
}

#[tauri::command]
pub(crate) fn defer_update(
    app: AppHandle,
    window: WebviewWindow,
    host: tauri::State<'_, HostState>,
) -> BridgeResult<()> {
    authorize_hosted(&window, &host)?;
    let target = available_update(&host)?;
    defer(&target)?;
    *host
        .deferred_version
        .write()
        .map_err(|_| BridgeError::new("STATE_LOCK_FAILED", "The update lock was poisoned."))? =
        Some(target.version);
    publish(&app, &host);
    Ok(())
}

#[tauri::command]
pub(crate) fn skip_update(
    app: AppHandle,
    window: WebviewWindow,
    host: tauri::State<'_, HostState>,
) -> BridgeResult<()> {
    authorize_hosted(&window, &host)?;
    let target = available_update(&host)?;
    skip(&target)?;
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
    publish(&app, &host);
    Ok(())
}

#[tauri::command]
pub(crate) fn install_update(
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
    windows::show_setup(&app)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_newer_plain_releases_are_selected() {
        assert_eq!(
            select_version(["0.1.1", "main", "0.2.0-beta.1", "0.1.2"], "0.1.0", None),
            Some("0.1.2".into())
        );
        assert_eq!(select_version(["0.1.0"], "0.1.0", None), None);
        assert_eq!(select_version(["0.1.2"], "0.1.0", Some("0.1.2")), None);
    }

    #[test]
    fn update_payload_marks_only_the_deferred_version() {
        let target = UpdateTarget {
            version: "0.1.2".into(),
            image_ref: format!("ghcr.io/omnideck-dev/omnideck@sha256:{}", "a".repeat(64)),
        };
        assert!(payload(&target, Some("0.1.2")).deferred);
        assert!(!payload(&target, Some("0.1.1")).deferred);
    }
}

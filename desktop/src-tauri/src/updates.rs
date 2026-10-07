use crate::{
    navigation::{authorize_hosted, is_hosted_app_url},
    platform,
    runtime::{BridgeError, BridgeResult, HostState},
    state, windows,
};
use reqwest::header::{ACCEPT, AUTHORIZATION};
use serde::{Deserialize, Serialize};
use std::{
    fs,
    path::Path,
    sync::{
        atomic::{AtomicU64, Ordering},
        Mutex,
    },
    time::Duration,
};
use tauri::{AppHandle, Manager, WebviewWindow};
use tauri_plugin_notification::NotificationExt;

const UPDATE_STATE_SCHEMA: u32 = 1;
const REPOSITORY: &str = "omnideck-dev/omnideck";
const REGISTRY: &str = "https://ghcr.io";
const MANIFEST_TYPES: &str = "application/vnd.oci.image.index.v1+json,application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.docker.distribution.manifest.v2+json";
const FIRST_CHECK: Duration = Duration::from_secs(10);
const CHECK_INTERVAL: Duration = Duration::from_secs(6 * 60 * 60);
const PREFERENCES_TIMEOUT: Duration = Duration::from_secs(5);
// Disk state is the authority. Never keep this lock across an HTTP request.
static UPDATE_STATE_LOCK: Mutex<()> = Mutex::new(());
static PREFERENCES_REVISION: AtomicU64 = AtomicU64::new(0);
static CHECK_SEQUENCE: AtomicU64 = AtomicU64::new(0);
static LAST_APPLIED_CHECK: AtomicU64 = AtomicU64::new(0);

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
    let _guard = UPDATE_STATE_LOCK
        .lock()
        .unwrap_or_else(|error| error.into_inner());
    update_state_path()
        .map(|path| read_state_at(&path))
        .unwrap_or_default()
}

fn read_state_at(path: &Path) -> UpdateState {
    let Ok(value) = fs::read(path)
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

fn write_state_at(path: &Path, value: &UpdateState) -> BridgeResult<()> {
    let mut encoded = serde_json::to_vec_pretty(value)
        .map_err(|error| BridgeError::new("UPDATE_STATE_FAILED", error.to_string()))?;
    encoded.push(b'\n');
    state::write_atomic(path, &encoded)
}

fn mutate_state_at<T>(
    path: &Path,
    change: impl FnOnce(&mut UpdateState) -> BridgeResult<T>,
) -> BridgeResult<T> {
    let _guard = UPDATE_STATE_LOCK
        .lock()
        .unwrap_or_else(|error| error.into_inner());
    let mut state = read_state_at(path);
    let result = change(&mut state)?;
    write_state_at(path, &state)?;
    Ok(result)
}

fn mutate_state<T>(change: impl FnOnce(&mut UpdateState) -> BridgeResult<T>) -> BridgeResult<T> {
    mutate_state_at(&update_state_path()?, change)
}

fn target_from_state(value: &UpdateState) -> Option<UpdateTarget> {
    Some(UpdateTarget {
        version: value.version.clone()?,
        image_ref: value.image_ref.clone()?,
    })
}

fn known_update_in(state: &UpdateState, installed: &str) -> Option<UpdateTarget> {
    let target = target_from_state(state)?;
    select_version(
        std::iter::once(target.version.as_str()),
        installed,
        state.skipped_version.as_deref(),
    )?;
    Some(target)
}

pub(crate) fn pending_at_launch(installed: &str) -> Option<UpdateTarget> {
    let state = read_state();
    pending_in(&state, installed)
}

fn pending_in(state: &UpdateState, installed: &str) -> Option<UpdateTarget> {
    let target = known_update_in(state, installed)?;
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

// A successful registry response is authoritative, including withdrawal. Ignore
// older checks that finish after a newer check, and reapply the user's current
// Skip/Later/preferences rather than the snapshot from before the request.
fn reconcile_check(
    state: &mut UpdateState,
    found: Option<UpdateTarget>,
    installed: &str,
    sequence: u64,
    latest_sequence: &mut u64,
) -> (Option<UpdateTarget>, bool) {
    if sequence < *latest_sequence {
        return (known_update_in(state, installed), false);
    }
    let previous_version = state.version.clone();
    let found = found.filter(|target| {
        select_version(
            std::iter::once(target.version.as_str()),
            installed,
            state.skipped_version.as_deref(),
        )
        .is_some()
    });
    state.version = found.as_ref().map(|value| value.version.clone());
    state.image_ref = found.as_ref().map(|value| value.image_ref.clone());
    *latest_sequence = sequence;
    let newly_found = found
        .as_ref()
        .is_some_and(|target| previous_version.as_deref() != Some(target.version.as_str()));
    (found, newly_found)
}

async fn check(installed: &str) -> BridgeResult<(Option<UpdateTarget>, bool)> {
    let sequence = CHECK_SEQUENCE.fetch_add(1, Ordering::AcqRel) + 1;
    let skipped = read_state().skipped_version;
    let found = registry_update(installed, skipped.as_deref()).await?;
    mutate_state(|state| {
        // Setup may have finished while the registry request was pending.
        let latest_installed = state::read_setup_record()
            .map(|record| record.image_version)
            .unwrap_or_else(|| installed.to_owned());
        state.checked_at = Some(
            time::OffsetDateTime::now_utc()
                .format(&time::format_description::well_known::Rfc3339)
                .map_err(|error| BridgeError::new("UPDATE_STATE_FAILED", error.to_string()))?,
        );
        let mut latest_sequence = LAST_APPLIED_CHECK.load(Ordering::Acquire);
        let result = reconcile_check(
            state,
            found,
            &latest_installed,
            sequence,
            &mut latest_sequence,
        );
        LAST_APPLIED_CHECK.store(latest_sequence, Ordering::Release);
        Ok(result)
    })
}

pub(crate) fn complete() -> BridgeResult<()> {
    mutate_state(|state| {
        state.deferred_version = None;
        let target = known_update_in(state, &installed_version());
        state.version = target.as_ref().map(|value| value.version.clone());
        state.image_ref = target.as_ref().map(|value| value.image_ref.clone());
        Ok(())
    })
}

#[derive(Clone, Copy, Default, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct UpdatePreferences {
    automatic: Option<bool>,
    notify: Option<bool>,
}

fn apply_preferences(state: &mut UpdateState, preferences: UpdatePreferences) {
    if let Some(automatic) = preferences.automatic {
        state.automatic = automatic;
    }
    if let Some(notify) = preferences.notify {
        state.notify = notify;
    }
}

#[tauri::command]
pub(crate) fn set_update_preferences(
    window: WebviewWindow,
    host: tauri::State<'_, HostState>,
    preferences: UpdatePreferences,
) -> BridgeResult<()> {
    authorize_hosted(&window, &host)?;
    mutate_state(|state| {
        apply_preferences(state, preferences);
        // Invalidates any settings response captured before this user action.
        PREFERENCES_REVISION.fetch_add(1, Ordering::AcqRel);
        Ok(())
    })
}

pub(crate) fn payload(target: &UpdateTarget, deferred: Option<&str>) -> UpdatePayload {
    UpdatePayload {
        version: target.version.clone(),
        deferred: deferred == Some(target.version.as_str()),
    }
}

fn installed_version() -> String {
    state::read_setup_record()
        .map(|record| record.image_version)
        .unwrap_or_else(|| {
            state::image_manifest()
                .map(|manifest| manifest.image_version)
                .unwrap_or_default()
        })
}

fn current_payload(state: &UpdateState) -> Option<UpdatePayload> {
    let target = known_update_in(state, &installed_version())?;
    Some(payload(&target, state.deferred_version.as_deref()))
}

fn publish(app: &AppHandle) {
    // Serialize publication with state changes so an older completed check
    // cannot reannounce a version that has just been skipped.
    let _guard = UPDATE_STATE_LOCK
        .lock()
        .unwrap_or_else(|error| error.into_inner());
    let Ok(path) = update_state_path() else {
        return;
    };
    let payload = current_payload(&read_state_at(&path));
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
    let revision = PREFERENCES_REVISION.load(Ordering::Acquire);
    let preferences = fetch_preferences(port, PREFERENCES_TIMEOUT).await?;
    mutate_state(|state| {
        import_preferences(
            state,
            preferences,
            revision,
            PREFERENCES_REVISION.load(Ordering::Acquire),
        );
        Ok(())
    })
}

fn import_preferences(
    state: &mut UpdateState,
    preferences: SoftwareUpdatePreferences,
    requested_revision: u64,
    current_revision: u64,
) {
    if requested_revision == current_revision {
        apply_preferences(
            state,
            UpdatePreferences {
                automatic: preferences.software_updates_automatic,
                notify: preferences.software_updates_notify,
            },
        );
    }
}

async fn fetch_preferences(
    port: u16,
    timeout: Duration,
) -> BridgeResult<SoftwareUpdatePreferences> {
    reqwest::Client::builder()
        .no_proxy()
        .timeout(timeout)
        .build()
        .map_err(|error| BridgeError::new("UPDATE_PREFERENCES_FAILED", error.to_string()))?
        .get(format!("http://127.0.0.1:{port}/api/settings"))
        .send()
        .await
        .and_then(reqwest::Response::error_for_status)
        .map_err(|error| BridgeError::new("UPDATE_PREFERENCES_FAILED", error.to_string()))?
        .json::<SoftwareUpdatePreferences>()
        .await
        .map_err(|error| BridgeError::new("UPDATE_PREFERENCES_FAILED", error.to_string()))
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

async fn perform_check(app: &AppHandle) -> BridgeResult<Option<UpdateTarget>> {
    let installed = installed_version();
    if installed.is_empty() {
        return Ok(None);
    }
    let (checked_target, newly_found) = check(&installed).await?;
    publish(app);
    let persisted = read_state();
    let found = known_update_in(&persisted, &installed_version());
    if let Some(found) = &found {
        if newly_found
            && checked_target.as_ref() == Some(found)
            && persisted.notify
            && !window_is_in_sight(app)
        {
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
            if let Err(error) = perform_check(&app).await {
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
    Ok(current_payload(&read_state()))
}

#[tauri::command]
pub(crate) async fn check_for_update(
    app: AppHandle,
    window: WebviewWindow,
    host: tauri::State<'_, HostState>,
) -> BridgeResult<Option<UpdatePayload>> {
    authorize_hosted(&window, &host)?;
    remember_preferences(&host).await?;
    perform_check(&app).await?;
    current_update(window, host)
}

fn available_update(state: &UpdateState) -> BridgeResult<UpdateTarget> {
    known_update_in(state, &installed_version())
        .ok_or_else(|| BridgeError::new("UPDATE_MISSING", "There is no update to act on."))
}

#[tauri::command]
pub(crate) fn defer_update(
    app: AppHandle,
    window: WebviewWindow,
    host: tauri::State<'_, HostState>,
) -> BridgeResult<()> {
    authorize_hosted(&window, &host)?;
    mutate_state(|state| {
        let target = available_update(state)?;
        state.deferred_version = Some(target.version);
        Ok(())
    })?;
    publish(&app);
    Ok(())
}

#[tauri::command]
pub(crate) fn skip_update(
    app: AppHandle,
    window: WebviewWindow,
    host: tauri::State<'_, HostState>,
) -> BridgeResult<()> {
    authorize_hosted(&window, &host)?;
    mutate_state(|state| {
        let target = available_update(state)?;
        state.skipped_version = Some(target.version);
        state.deferred_version = None;
        state.version = None;
        state.image_ref = None;
        Ok(())
    })?;
    publish(&app);
    Ok(())
}

#[tauri::command]
pub(crate) fn install_update(
    app: AppHandle,
    window: WebviewWindow,
    host: tauri::State<'_, HostState>,
) -> BridgeResult<()> {
    authorize_hosted(&window, &host)?;
    let target = available_update(&read_state())?;
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

    fn target(version: &str) -> UpdateTarget {
        UpdateTarget {
            version: version.into(),
            image_ref: format!("ghcr.io/omnideck-dev/omnideck@sha256:{}", "a".repeat(64)),
        }
    }

    fn reconcile(
        state: &mut UpdateState,
        found: Option<UpdateTarget>,
        installed: &str,
    ) -> Option<UpdateTarget> {
        reconcile_check(state, found, installed, 1, &mut 0).0
    }

    #[test]
    fn late_check_preserves_skip_and_preferences() {
        let mut state = UpdateState {
            skipped_version: Some("0.5.3".into()),
            automatic: false,
            notify: false,
            ..UpdateState::default()
        };
        assert_eq!(reconcile(&mut state, Some(target("0.5.3")), "0.5.2"), None);
        assert_eq!(state.skipped_version.as_deref(), Some("0.5.3"));
        assert!(!state.automatic);
        assert!(!state.notify);
        assert!(state.version.is_none());
    }

    #[test]
    fn checks_preserve_later_and_revalidate_the_installed_version() {
        let mut state = UpdateState::default();
        reconcile(&mut state, Some(target("0.5.4")), "0.5.2");
        state.deferred_version = Some("0.5.4".into());
        assert_eq!(
            reconcile(&mut state, Some(target("0.5.4")), "0.5.2"),
            Some(target("0.5.4"))
        );
        assert_eq!(state.deferred_version.as_deref(), Some("0.5.4"));
        assert_eq!(reconcile(&mut state, Some(target("0.5.4")), "0.5.4"), None);
    }

    #[test]
    fn withdrawn_release_clears_and_older_checks_cannot_resurrect_it() {
        let mut state = UpdateState::default();
        let mut latest = 0;
        assert_eq!(
            reconcile_check(&mut state, Some(target("0.5.4")), "0.5.2", 2, &mut latest),
            (Some(target("0.5.4")), true)
        );
        // A slower, older check cannot replace the newer answer.
        assert_eq!(
            reconcile_check(&mut state, Some(target("0.5.3")), "0.5.2", 1, &mut latest),
            (Some(target("0.5.4")), false)
        );
        assert_eq!(
            reconcile_check(&mut state, None, "0.5.2", 1, &mut latest),
            (Some(target("0.5.4")), false)
        );
        // A fresh successful check confirms the registry withdrew the release.
        assert_eq!(
            reconcile_check(&mut state, None, "0.5.2", 4, &mut latest),
            (None, false)
        );
        assert!(state.version.is_none());
        assert!(state.image_ref.is_none());
        assert_eq!(
            reconcile_check(&mut state, Some(target("0.5.4")), "0.5.2", 3, &mut latest),
            (None, false)
        );
        assert!(current_payload(&state).is_none());
    }

    #[test]
    fn settings_response_started_before_user_save_cannot_restore_old_preferences() {
        let mut state = UpdateState::default();
        apply_preferences(
            &mut state,
            UpdatePreferences {
                automatic: Some(false),
                notify: Some(false),
            },
        );
        import_preferences(
            &mut state,
            SoftwareUpdatePreferences {
                software_updates_automatic: Some(true),
                software_updates_notify: Some(true),
            },
            1,
            2,
        );
        assert!(!state.automatic);
        assert!(!state.notify);
        import_preferences(
            &mut state,
            SoftwareUpdatePreferences {
                software_updates_automatic: None,
                software_updates_notify: Some(true),
            },
            2,
            2,
        );
        assert!(!state.automatic);
        assert!(state.notify);
    }

    #[test]
    fn disabled_automatic_updates_are_persisted_before_next_launch() {
        let directory = std::env::temp_dir().join(format!(
            "omnideck-update-preferences-{}",
            std::process::id()
        ));
        fs::create_dir_all(&directory).unwrap();
        let path = directory.join("update-state.json");
        mutate_state_at(&path, |state| {
            reconcile(state, Some(target("0.5.3")), "0.5.2");
            apply_preferences(
                state,
                UpdatePreferences {
                    automatic: Some(false),
                    notify: None,
                },
            );
            Ok(())
        })
        .unwrap();
        let mut relaunched = read_state_at(&path);
        assert!(pending_in(&relaunched, "0.5.2").is_none());
        relaunched.deferred_version = Some("0.5.3".into());
        assert_eq!(pending_in(&relaunched, "0.5.2"), Some(target("0.5.3")));
        fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn concurrent_update_transactions_preserve_every_change() {
        let directory = std::env::temp_dir().join(format!(
            "omnideck-update-transactions-{}",
            std::process::id()
        ));
        fs::create_dir_all(&directory).unwrap();
        let path = directory.join("update-state.json");
        write_state_at(&path, &UpdateState::default()).unwrap();
        let workers: Vec<_> = (0..16)
            .map(|_| {
                let path = path.clone();
                std::thread::spawn(move || {
                    mutate_state_at(&path, |state| {
                        let count = state
                            .checked_at
                            .as_deref()
                            .unwrap_or("0")
                            .parse::<u32>()
                            .unwrap();
                        std::thread::yield_now();
                        state.checked_at = Some((count + 1).to_string());
                        Ok(())
                    })
                    .unwrap()
                })
            })
            .collect();
        for worker in workers {
            worker.join().unwrap();
        }
        assert_eq!(read_state_at(&path).checked_at.as_deref(), Some("16"));
        fs::remove_dir_all(directory).unwrap();
    }

    #[tokio::test]
    async fn preferences_fetch_times_out_on_stalled_response_body() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            let mut request = [0; 1024];
            let received = stream.read(&mut request).await.unwrap();
            assert!(
                received > 0,
                "the client must send a request before the server stalls"
            );
            stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\nContent-Type: application/json\r\n\r\n{").await.unwrap();
            std::future::pending::<()>().await;
        });
        let result = tokio::time::timeout(
            Duration::from_secs(2),
            fetch_preferences(port, Duration::from_millis(100)),
        )
        .await;
        server.abort();
        let error = result
            .expect("the preferences request must have a deadline")
            .err()
            .expect("an incomplete JSON response must time out");
        assert_eq!(error.code, "UPDATE_PREFERENCES_FAILED");
    }
}

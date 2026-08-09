use serde::{Deserialize, Serialize};
use std::{collections::HashMap, sync::OnceLock};

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CopyEntry {
    pub title: String,
    pub detail: String,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Phase {
    pub id: String,
    pub label: String,
    pub activity: String,
    pub applies_to: Option<Vec<String>>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FailureCopy {
    pub phase: Option<String>,
    pub result: String,
    pub title: String,
    pub detail: String,
    pub value: String,
    pub can_retry: bool,
    pub primary_action: Option<String>,
    pub primary_label: Option<String>,
    pub secondary_action: Option<String>,
    pub secondary_label: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ParityContract {
    setup_copy: HashMap<String, CopyEntry>,
    setup_phases: Vec<Phase>,
    failure_copy: HashMap<String, FailureCopy>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Diagnostic {
    pub id: String,
    pub label: String,
    pub status: String,
    pub value: String,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SetupState {
    pub stage: String,
    pub title: String,
    pub detail: String,
    pub progress: Option<f64>,
    pub indeterminate: bool,
    pub step: Option<usize>,
    pub total_steps: usize,
    pub status: Option<String>,
    pub can_start: bool,
    pub can_retry: bool,
    pub can_open: bool,
    pub activity: Option<String>,
    pub primary_action: Option<String>,
    pub primary_label: Option<String>,
    pub secondary_action: Option<String>,
    pub secondary_label: Option<String>,
    pub setup_reason: String,
    pub diagnostics: Option<Vec<Diagnostic>>,
    pub diagnostic_result: Option<String>,
    pub technical: Option<String>,
}

fn contract() -> &'static ParityContract {
    static CONTRACT: OnceLock<ParityContract> = OnceLock::new();
    CONTRACT.get_or_init(|| {
        serde_json::from_str(include_str!("../setup-parity.json"))
            .expect("the Electron setup parity contract must be valid")
    })
}

pub fn phases() -> &'static [Phase] {
    static PHASES: OnceLock<Vec<Phase>> = OnceLock::new();
    PHASES.get_or_init(|| phases_for(crate::platform::KEY))
}

fn phases_for(platform: &str) -> Vec<Phase> {
    contract()
        .setup_phases
        .iter()
        .filter(|phase| {
            phase
                .applies_to
                .as_ref()
                .is_none_or(|platforms| platforms.iter().any(|candidate| candidate == platform))
        })
        .cloned()
        .collect()
}

pub fn copy_state(
    stage: &str,
    copy: &str,
    reason: &str,
    progress: Option<f64>,
    activity: Option<String>,
) -> SetupState {
    let copy = contract()
        .setup_copy
        .get(copy)
        .expect("known Electron setup copy");
    SetupState {
        stage: stage.to_owned(),
        title: copy.title.clone(),
        detail: copy.detail.clone(),
        progress,
        indeterminate: false,
        step: None,
        total_steps: steps().len(),
        status: None,
        can_start: false,
        can_retry: false,
        can_open: false,
        activity,
        primary_action: None,
        primary_label: None,
        secondary_action: None,
        secondary_label: None,
        setup_reason: reason.to_owned(),
        diagnostics: None,
        diagnostic_result: None,
        technical: None,
    }
}

pub fn welcome() -> SetupState {
    let mut state = copy_state("welcome", "welcome", "first-run", None, None);
    state.can_start = true;
    state
}

pub fn working(reason: &str, phase_index: Option<usize>, fraction: f64) -> SetupState {
    let copy = match reason {
        "update" => "updating",
        "resume" => "resuming",
        _ => "preparing",
    };
    let activity = phase_index.map(|index| phases()[index].activity.clone());
    let progress = phase_index.map(|_| fraction.clamp(0.0, 1.0));
    let mut state = copy_state("preparing", copy, reason, progress, activity);
    state.progress = phase_index.map(|_| fraction.clamp(0.0, 1.0));
    state.indeterminate = phase_index.is_none();
    state.step = phase_index.map(|index| index + 1);
    state
}

pub fn working_step(
    reason: &str,
    step_id: Option<&str>,
    progress: Option<f64>,
    activity: Option<String>,
    status: Option<String>,
) -> SetupState {
    let copy = match step_id {
        Some("wsl-permission") => "permissionWindows",
        Some("macos-permission") => "permissionMacos",
        Some("linux-permission") => "permission",
        _ => match reason {
            "update" => "updating",
            "resume" => "resuming",
            _ => "preparing",
        },
    };
    let mut state = copy_state("preparing", copy, reason, progress, activity);
    state.indeterminate = progress.is_none();
    state.step = step_id.and_then(step_index);
    state.status = status.filter(|value| !value.trim().is_empty());
    state
}

pub fn ready(reason: &str) -> SetupState {
    let mut state = copy_state("ready", "ready", reason, None, None);
    state.can_open = true;
    state
}

pub fn error(kind: &str, reason: &str, reached: usize, technical: String) -> SetupState {
    let copy = contract()
        .failure_copy
        .get(kind)
        .or_else(|| contract().failure_copy.get("unknown"))
        .expect("unknown failure copy must exist");
    let failed_index = copy
        .phase
        .as_deref()
        .and_then(|id| phases().iter().position(|phase| phase.id == id));
    let diagnostics = phases()
        .iter()
        .enumerate()
        .map(|(index, phase)| {
            if Some(index) == failed_index {
                return Diagnostic {
                    id: phase.id.clone(),
                    label: phase.label.clone(),
                    status: "issue".into(),
                    value: copy.value.clone(),
                };
            }
            let passed = index < failed_index.unwrap_or(reached);
            Diagnostic {
                id: phase.id.clone(),
                label: phase.label.clone(),
                status: if passed { "pass" } else { "waiting" }.into(),
                value: if passed { "Done" } else { "Not started" }.into(),
            }
        })
        .collect();
    SetupState {
        stage: "error".into(),
        title: copy.title.clone(),
        detail: copy.detail.clone(),
        progress: None,
        indeterminate: false,
        step: None,
        total_steps: steps().len(),
        status: None,
        can_start: false,
        can_retry: copy.can_retry,
        can_open: false,
        activity: None,
        primary_action: copy.primary_action.clone(),
        primary_label: copy.primary_label.clone(),
        secondary_action: copy.secondary_action.clone(),
        secondary_label: copy.secondary_label.clone(),
        setup_reason: reason.to_owned(),
        diagnostics: Some(diagnostics),
        diagnostic_result: Some(copy.result.clone()),
        technical: Some(technical.chars().take(4_000).collect()),
    }
}

pub fn phase_index(id: &str) -> Option<usize> {
    phases().iter().position(|phase| phase.id == id)
}

const WINDOWS_STEPS: &[&str] = &[
    "wsl-permission",
    "wsl-enable",
    "windows-restart",
    "podman-download",
    "podman-install",
    "secure-space",
    "app-download",
    "startup",
];
const MACOS_STEPS: &[&str] = &[
    "podman-download",
    "macos-permission",
    "podman-install",
    "secure-space",
    "app-download",
    "startup",
];
const LINUX_STEPS: &[&str] = &[
    "linux-permission",
    "package-index",
    "podman-install",
    "app-download",
    "startup",
];

fn steps_for(platform: &str) -> &'static [&'static str] {
    match platform {
        "win32" => WINDOWS_STEPS,
        "darwin" => MACOS_STEPS,
        _ => LINUX_STEPS,
    }
}

pub fn steps() -> &'static [&'static str] {
    steps_for(crate::platform::KEY)
}

pub fn step_index(id: &str) -> Option<usize> {
    steps()
        .iter()
        .position(|candidate| *candidate == id)
        .map(|index| index + 1)
}

pub fn first_step() -> &'static str {
    steps()[0]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ready_copy_and_progress_match_electron() {
        let state = ready("first-run");
        assert_eq!(state.title, "omnideck is ready");
        assert_eq!(
            state.detail,
            "Everything is prepared. Open omnideck whenever you’re ready."
        );
        assert_eq!(state.progress, None);
        assert_eq!(state.total_steps, 5);
        assert!(state.can_open);
    }

    #[test]
    fn windows_phase_weights_match_electron() {
        let phases = phases_for("win32");
        assert_eq!(phases.len(), 4);
        assert_eq!(phases[2].id, "download");
    }

    #[test]
    fn linux_drops_the_managed_environment_phase() {
        let phases = phases_for("linux");
        assert_eq!(
            phases
                .iter()
                .map(|phase| phase.id.as_str())
                .collect::<Vec<_>>(),
            ["software", "download", "startup"]
        );
    }

    #[test]
    fn macos_downloads_before_requesting_approval() {
        assert_eq!(
            steps_for("darwin"),
            [
                "podman-download",
                "macos-permission",
                "podman-install",
                "secure-space",
                "app-download",
                "startup",
            ]
        );
        let permission = working_step(
            "first-run",
            Some("macos-permission"),
            None,
            Some("Waiting for approval from macOS…".into()),
            Some("Waiting for approval".into()),
        );
        assert_eq!(
            permission.detail,
            "Your Mac will ask you to approve installing Podman. omnideck never sees or stores your password."
        );
    }

    #[test]
    fn errors_use_the_inline_technical_details_without_a_redundant_action() {
        let state = error("windowsFeatures", "first-run", 0, "details".into());
        assert_eq!(state.secondary_action, None);
        assert_eq!(state.secondary_label, None);

        let restart = error("restart", "first-run", 0, "restart".into());
        assert_eq!(restart.secondary_action.as_deref(), Some("close"));
        assert_eq!(restart.secondary_label.as_deref(), Some("Restart later"));
    }
}

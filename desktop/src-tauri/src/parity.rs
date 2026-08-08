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
    pub weight: f64,
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
    let progress = phase_index.map(|index| overall_progress(index, fraction));
    let activity = phase_index.map(|index| phases()[index].activity.clone());
    let mut state = copy_state("preparing", copy, reason, progress, activity);
    state.indeterminate = phase_index.is_none();
    state
}

pub fn ready(reason: &str) -> SetupState {
    let mut state = copy_state("ready", "ready", reason, Some(1.0), None);
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
        can_start: false,
        can_retry: copy.can_retry,
        can_open: false,
        activity: None,
        primary_action: copy.primary_action.clone(),
        primary_label: copy.primary_label.clone(),
        secondary_action: copy
            .secondary_action
            .clone()
            .or_else(|| Some("show-logs".into())),
        secondary_label: copy
            .secondary_label
            .clone()
            .or_else(|| Some("Show diagnostic log".into())),
        setup_reason: reason.to_owned(),
        diagnostics: Some(diagnostics),
        diagnostic_result: Some(copy.result.clone()),
        technical: Some(technical.chars().take(4_000).collect()),
    }
}

pub fn phase_index(id: &str) -> Option<usize> {
    phases().iter().position(|phase| phase.id == id)
}

fn overall_progress(index: usize, fraction: f64) -> f64 {
    let total: f64 = phases().iter().map(|phase| phase.weight).sum();
    let done: f64 = phases().iter().take(index).map(|phase| phase.weight).sum();
    let current = phases()[index].weight * fraction.clamp(0.0, 1.0);
    ((done + current) / total).clamp(0.0, 1.0)
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
        assert_eq!(state.progress, Some(1.0));
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
        assert_eq!(phases.iter().map(|phase| phase.weight).sum::<f64>(), 85.0);
    }
}

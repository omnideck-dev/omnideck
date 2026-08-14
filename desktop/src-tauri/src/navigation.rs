use crate::runtime::{BridgeError, BridgeResult, HostState};
use tauri::WebviewWindow;

pub(crate) fn is_local_setup_url(url: &tauri::Url) -> bool {
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

pub(crate) fn is_hosted_app_url(url: &tauri::Url, expected_port: Option<u16>) -> bool {
    url.scheme() == "http"
        && url.host_str() == Some("127.0.0.1")
        && expected_port.is_some()
        && url.port() == expected_port
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum HostedNavigation {
    Allow,
    OpenExternal,
    Deny,
}

pub(crate) fn hosted_navigation(url: &tauri::Url, expected_port: Option<u16>) -> HostedNavigation {
    if is_hosted_placeholder_url(url) || is_hosted_app_url(url, expected_port) {
        HostedNavigation::Allow
    } else if matches!(url.scheme(), "http" | "https") {
        HostedNavigation::OpenExternal
    } else {
        HostedNavigation::Deny
    }
}

pub(crate) fn authorize_local_setup(window: &WebviewWindow) -> BridgeResult<()> {
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

pub(crate) fn authorize_hosted(window: &WebviewWindow, host: &HostState) -> BridgeResult<()> {
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
    fn hosted_app_stays_local_and_web_links_open_externally() {
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
}

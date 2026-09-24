use std::path::Path;
use tauri::webview::DownloadEvent;

pub(crate) fn handle<R: tauri::Runtime>(
    webview: tauri::Webview<R>,
    event: DownloadEvent<'_>,
) -> bool {
    if let DownloadEvent::Finished { url, path, success } = event {
        let _ = webview.eval(feedback_script(&url, path.as_deref(), success));
    }
    true
}

pub(crate) fn feedback_script(url: &tauri::Url, path: Option<&Path>, success: bool) -> String {
    let filename = path
        .and_then(Path::file_name)
        .and_then(|value| value.to_str())
        .map(str::to_owned)
        .or_else(|| {
            url.path_segments()
                .and_then(|mut segments| segments.next_back())
                .filter(|value| !value.is_empty())
                .map(str::to_owned)
        })
        .unwrap_or_else(|| "download".into());
    let payload = serde_json::json!({ "filename": filename, "success": success });
    format!(
        "(() => {{ const detail = {payload}; window.__omnideckPendingDownload = detail; \
         window.dispatchEvent(new CustomEvent('omnideck:download', {{ detail }})); }})();"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn feedback_is_retained_until_the_ui_consumes_it() {
        let url = "http://127.0.0.1:2337/api/profiles/export".parse().unwrap();
        let script = feedback_script(
            &url,
            Some(Path::new("/home/tester/Downloads/agent.json")),
            true,
        );
        assert!(script.contains("__omnideckPendingDownload = detail"));
        assert!(script.contains("omnideck:download"));
        assert!(script.contains(r#""filename":"agent.json""#));
        assert!(script.contains(r#""success":true"#));
    }
}

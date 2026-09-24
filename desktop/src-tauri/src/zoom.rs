use tauri::{Manager, Runtime, WebviewWindowBuilder};

pub(crate) fn with_native_hotkeys<'a, R: Runtime, M: Manager<R>>(
    builder: WebviewWindowBuilder<'a, R, M>,
) -> WebviewWindowBuilder<'a, R, M> {
    builder.zoom_hotkeys_enabled(true)
}

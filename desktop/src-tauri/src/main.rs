#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    #[cfg(target_os = "linux")]
    if let Some(app_dir) = std::env::var_os("APPDIR") {
        let library_arch = match std::env::consts::ARCH {
            "x86_64" => "x86_64-linux-gnu",
            "aarch64" => "aarch64-linux-gnu",
            _ => "",
        };
        let module_dir = std::path::PathBuf::from(app_dir)
            .join("usr/lib")
            .join(library_arch)
            .join("gio/modules");
        if module_dir.is_dir() {
            // linuxdeploy otherwise lets the bundled GLib discover host GIO
            // modules. Those modules can target a newer GLib ABI and crash
            // AppImage file input before the application sees the upload.
            std::env::set_var("GIO_MODULE_DIR", module_dir);
        }
    }
    omnideck_tauri_host::run();
}

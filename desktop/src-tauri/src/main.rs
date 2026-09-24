#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    #[cfg(target_os = "linux")]
    if let Some(app_dir) = std::env::var_os("APPDIR") {
        // linuxdeploy's Python hook points these variables into the ephemeral
        // AppDir. They are useful while assembling the image, but allowing the
        // packaged host to pass them to its sidecar breaks host Python tools
        // such as apt's helpers when setup elevates through pkexec.
        std::env::remove_var("PYTHONHOME");
        std::env::remove_var("PYTHONPATH");

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

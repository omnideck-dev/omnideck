fn main() {
    // Keep clean Windows installs independent of an external VC++ runtime.
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .windows_attributes(tauri_build::WindowsAttributes::new().static_vc_runtime(true)),
    )
    .expect("failed to build desktop resources");
}

fn main() {
    // tauri-build 2.6 uses this flag to avoid requiring VC++ DLLs on clean Windows
    // installs. CLI 2.12 stopped supplying it; keep the policy here until we move
    // to tauri-build 2.7's WindowsAttributes::static_vc_runtime API.
    std::env::set_var("STATIC_VCRUNTIME", "true");
    tauri_build::build();
}

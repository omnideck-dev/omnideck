macro_rules! handler {
    () => {
        tauri::generate_handler![
            crate::runtime::bootstrap,
            crate::runtime::begin_setup,
            crate::runtime::open_app,
            crate::runtime::run_action,
            crate::navigation::open_external,
            crate::updates::current_update,
            crate::updates::check_for_update,
            crate::updates::install_update,
            crate::updates::defer_update,
            crate::updates::skip_update,
            crate::updates::set_update_preferences
        ]
    };
}

pub(crate) use handler;

// Maku's desktop shell: one window for the UI, with the engine running beside it.
// See docs/stack/tauri.md.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod choices;
mod dialogs;
mod engine;
mod explorer;
mod links;
mod look;
mod process;
mod tray;
mod updater;

use tauri::{Manager, RunEvent, WindowEvent};

fn main() {
    let app = tauri::Builder::default()
        // Opening Maku again shows the window that's already open (or waiting in the tray):
        // two copies would share one database.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            tray::show(app);
        }))
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(
            tauri_plugin_autostart::Builder::new()
                .arg(tray::IN_TRAY)
                .build(),
        )
        .manage(engine::Engine::default())
        .manage(updater::PendingUpdate::default())
        .manage(tray::Tray::default())
        .invoke_handler(tauri::generate_handler![
            engine::engine_status,
            engine::restart_engine,
            updater::prepare_update,
            updater::install_update,
            links::open_downloads_page,
            links::open_tmdb_api_page,
            links::open_tmdb_page,
            dialogs::pick_folder,
            dialogs::pick_export,
            explorer::open_folder,
            explorer::show_in_folder,
            tray::start_with_windows,
            tray::set_start_with_windows,
            tray::keep_in_tray,
            tray::set_keep_in_tray,
            look::look,
            look::set_look,
            look::scheme,
            look::set_scheme,
        ])
        .on_window_event(|window, event| match event {
            // As the owner chose in Settings > General, closing the window keeps Maku working in
            // the tray, or quits it.
            WindowEvent::CloseRequested { api, .. }
                if window.app_handle().state::<tray::Tray>().keeps() =>
            {
                api.prevent_close();
                let _ = window.hide();
            }
            // Light or dark changed: Windows' own setting, or the owner's choice.
            WindowEvent::ThemeChanged(theme) => look::follow(window, *theme),
            _ => {}
        })
        .setup(|app| {
            tray::set_up(app.handle())?;
            look::make_window(app.handle())?;
            if !tray::started_in_tray(std::env::args()) {
                tray::show(app.handle());
            }
            engine::start(app.handle().clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Maku's window couldn't be created");

    app.run(|app, event| {
        if let RunEvent::Exit = event {
            app.state::<engine::Engine>().stop();
        }
    });
}

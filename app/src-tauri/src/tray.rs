//! Maku in the notification area (the tray): an icon while it runs, to open the window or quit.
//! With "Start with Windows" on, Maku starts there when Windows signs in. With "Keep Maku running
//! when you close the window" on, closing the window keeps it there, so the queue, the backups
//! and the watching carry on; off, closing the window quits Maku. What the engine tells of (a
//! finished batch, a paused queue) comes as a Windows notification while the window is away, and
//! as a note in the window (the `notice` event) while it's open.

use std::sync::atomic::{AtomicBool, Ordering};

use serde::Serialize;
use serde_json::Value;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_autostart::ManagerExt;
use tauri_plugin_notification::NotificationExt;

use crate::choices;

/// What Windows starts Maku with at sign-in: wait in the tray, the window hidden.
pub const IN_TRAY: &str = "--in-tray";

/// Whether closing the window keeps Maku in the tray: the owner's choice in Settings > General.
#[derive(Default)]
pub struct Tray {
    keep: AtomicBool,
}

impl Tray {
    pub fn keeps(&self) -> bool {
        self.keep.load(Ordering::Relaxed)
    }
}

/// The icon and its menu, and a click on a notification opening the window. Run once, at start.
pub fn set_up(app: &AppHandle) -> tauri::Result<()> {
    let keep = saved_choice(app).unwrap_or_else(|| {
        // Before closing was a choice of its own, it kept Maku in the tray with "Start with
        // Windows" on: so it still does, until the owner chooses.
        let keep = app.autolaunch().is_enabled().unwrap_or(false);
        let _ = save_choice(app, keep);
        keep
    });
    app.state::<Tray>().keep.store(keep, Ordering::Relaxed);
    let open = MenuItem::with_id(app, "open", "Open Maku", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit Maku", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &quit])?;
    let mut tray = TrayIconBuilder::with_id("maku")
        .tooltip("Maku")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "open" => show(app),
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    let handle = app.clone();
    let _ = app.notification().on_action(move |_| show(&handle));
    Ok(())
}

/// Brings the window back: from the tray, from the taskbar, or from behind other windows.
pub fn show(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

/// What the window shows of a notification while it's open. Mirrors `Notice` in
/// app/src/components/shell/notices.tsx.
#[derive(Clone, Serialize)]
struct Notice<'a> {
    title: &'a str,
    body: &'a str,
    /// Where in Maku it leads: "/titles/12".
    link: Option<&'a str>,
}

/// Tells the owner: a note in the window while it's in front of them, else a Windows
/// notification (a click on it opens the window).
pub fn tell(app: &AppHandle, title: &str, body: &str, link: Option<&str>) {
    if window_open(app) {
        let _ = app.emit("notice", Notice { title, body, link });
    } else {
        tell_away(app, title, body);
    }
}

/// A Windows notification, unless the window is in front of the owner: it shows the same itself.
pub fn tell_away(app: &AppHandle, title: &str, body: &str) {
    if !window_open(app) {
        let _ = app.notification().builder().title(title).body(body).show();
    }
}

/// Whether the window is in front of the owner: shown, and not minimized.
pub fn window_open(app: &AppHandle) -> bool {
    app.get_webview_window("main").is_some_and(|window| {
        window.is_visible().unwrap_or(false) && !window.is_minimized().unwrap_or(false)
    })
}

/// Whether Windows started Maku at sign-in, to wait in the tray.
pub fn started_in_tray(args: impl IntoIterator<Item = String>) -> bool {
    args.into_iter().any(|arg| arg == IN_TRAY)
}

/// Whether Maku starts with Windows, in the tray.
#[tauri::command]
pub fn start_with_windows(app: AppHandle) -> Result<bool, String> {
    app.autolaunch()
        .is_enabled()
        .map_err(|error| format!("Windows didn't say ({error})."))
}

/// Starts Maku with Windows, in the tray, or stops that.
#[tauri::command]
pub fn set_start_with_windows(app: AppHandle, on: bool) -> Result<bool, String> {
    let autolaunch = app.autolaunch();
    let done = if on {
        autolaunch.enable()
    } else {
        autolaunch.disable()
    };
    done.map_err(|error| format!("Windows didn't take that ({error})."))?;
    Ok(on)
}

/// Whether closing the window keeps Maku running in the tray.
#[tauri::command]
pub fn keep_in_tray(app: AppHandle) -> Result<bool, String> {
    Ok(app.state::<Tray>().keeps())
}

/// Closing the window keeps Maku running in the tray, or quits it: from now, and at every start.
#[tauri::command]
pub fn set_keep_in_tray(app: AppHandle, on: bool) -> Result<bool, String> {
    save_choice(&app, on)?;
    app.state::<Tray>().keep.store(on, Ordering::Relaxed);
    Ok(on)
}

/// Where the shell keeps that choice, beside its others (choices.rs).
const KEEP: &str = "keepInTray";

fn saved_choice(app: &AppHandle) -> Option<bool> {
    kept(choices::read(app, KEEP))
}

fn save_choice(app: &AppHandle, on: bool) -> Result<(), String> {
    choices::save(app, KEEP, Value::Bool(on))
}

/// The choice kept, if one was: a true or false.
fn kept(choice: Option<Value>) -> Option<bool> {
    choice?.as_bool()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn maku_waits_in_the_tray_only_when_windows_started_it() {
        assert!(started_in_tray(["maku.exe".into(), IN_TRAY.into()]));
        assert!(!started_in_tray(["maku.exe".into()]));
    }

    #[test]
    fn closing_keeps_maku_in_the_tray_as_the_owner_chose() {
        assert_eq!(kept(Some(json!(true))), Some(true));
        assert_eq!(kept(Some(json!(false))), Some(false));
        // Never chosen, or a choice that isn't Maku's: start with Windows decides.
        assert_eq!(kept(None), None);
        assert_eq!(kept(Some(json!("yes"))), None);
    }
}

//! Maku's look, as the owner chose in Settings > General: light or dark (as Windows is, the
//! default, or always one) and one of four colour schemes (Velvet, the default, Lagoon, Dusk or
//! Graphite). The window's theme carries light or dark to the page, whose colours follow it
//! (app/src/styles/tokens.css); the scheme reaches the page before its first frame, and the
//! window's own colour under the page follows both.

use serde::{Deserialize, Serialize};
use tauri::window::Color;
use tauri::{AppHandle, Manager, Theme, WebviewWindow, WebviewWindowBuilder, Window};

use crate::choices;

/// The owner's choice of light or dark. Mirrors `Look` in app/src/lib/look.ts.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Look {
    /// Light or dark as Windows is, changing when it does.
    #[default]
    Windows,
    Light,
    Dark,
}

impl Look {
    /// The window's own theme: none follows Windows.
    fn theme(self) -> Option<Theme> {
        match self {
            Look::Windows => None,
            Look::Light => Some(Theme::Light),
            Look::Dark => Some(Theme::Dark),
        }
    }
}

/// The owner's choice of colours. Mirrors `Scheme` in app/src/lib/look.ts.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Scheme {
    /// Wine and crimson, brass for what's ready.
    #[default]
    Velvet,
    /// Deep teal.
    Lagoon,
    /// Indigo and coral pink.
    Dusk,
    /// Black and white.
    Graphite,
}

impl Scheme {
    /// The word the page knows it by: `data-scheme` on its <html>.
    fn word(self) -> &'static str {
        match self {
            Scheme::Velvet => "velvet",
            Scheme::Lagoon => "lagoon",
            Scheme::Dusk => "dusk",
            Scheme::Graphite => "graphite",
        }
    }

    /// Its window colour (--scheme-window) in light and in dark.
    fn windows(self) -> ([u8; 3], [u8; 3]) {
        match self {
            Scheme::Velvet => ([0xf6, 0xef, 0xea], [0x12, 0x0b, 0x0e]),
            Scheme::Lagoon => ([0xee, 0xf5, 0xf4], [0x06, 0x11, 0x13]),
            Scheme::Dusk => ([0xf3, 0xf1, 0xfa], [0x0c, 0x0a, 0x16]),
            Scheme::Graphite => ([0xf4, 0xf4, 0xf3], [0x0d, 0x0e, 0x10]),
        }
    }
}

const LOOK: &str = "look";
const SCHEME: &str = "scheme";

/// The look chosen; as Windows is when none was.
fn saved(app: &AppHandle) -> Look {
    choices::read(app, LOOK)
        .and_then(|value| serde_json::from_value(value).ok())
        .unwrap_or_default()
}

/// The scheme chosen; Velvet when none was.
fn saved_scheme(app: &AppHandle) -> Scheme {
    choices::read(app, SCHEME)
        .and_then(|value| serde_json::from_value(value).ok())
        .unwrap_or_default()
}

/// The window's own colour, under the page: the page's window colour in the scheme and theme.
fn window_colour(scheme: Scheme, theme: Theme) -> Color {
    let (light, dark) = scheme.windows();
    let [red, green, blue] = if theme == Theme::Light { light } else { dark };
    Color(red, green, blue, 0xff)
}

/// The page's own script for its scheme (app/src/lib/scheme-script.js, run by its tests): it puts
/// the scheme on <html> before the first frame, waiting for <html> when it runs before there is
/// one, or puts on the newer one a reload finds in the session.
const PAGE_SCRIPT: &str = include_str!("../../src/lib/scheme-script.js");

/// What the page runs before anything else: the scheme chosen, then the page's script, which
/// wears it before the first frame.
fn scheme_script(scheme: Scheme) -> String {
    format!(
        "window.__MAKU_SCHEME__ = \"{}\";\n{PAGE_SCRIPT}",
        scheme.word()
    )
}

/// Shows a choice on the window, then keeps it for every start, so the two never disagree: one
/// the window doesn't take isn't kept, and one that can't be kept comes off the window again.
fn show_then_keep<T: Copy>(
    chosen: T,
    kept: T,
    mut show: impl FnMut(T) -> Result<(), String>,
    keep: impl FnOnce(T) -> Result<(), String>,
) -> Result<T, String> {
    show(chosen)?;
    if let Err(error) = keep(chosen) {
        let _ = show(kept);
        return Err(error);
    }
    Ok(chosen)
}

/// Keeps a choice for every start.
fn keep(app: &AppHandle, key: &str, value: impl Serialize) -> Result<(), String> {
    let value = serde_json::to_value(value).map_err(|error| error.to_string())?;
    choices::save(app, key, value)
}

/// Makes Maku's window, hidden, in the look and scheme chosen, so the page is light or dark and
/// in its colours from its first frame. Everything else about the window is in tauri.conf.json.
pub fn make_window(app: &AppHandle) -> tauri::Result<WebviewWindow> {
    let config = app
        .config()
        .app
        .windows
        .iter()
        .find(|window| window.label == "main")
        .ok_or(tauri::Error::WindowNotFound)?;
    let scheme = saved_scheme(app);
    let window = WebviewWindowBuilder::from_config(app, config)?
        .theme(saved(app).theme())
        .initialization_script(scheme_script(scheme))
        .build()?;
    window.set_background_color(Some(window_colour(scheme, window.theme()?)))?;
    Ok(window)
}

/// The window's colour follows its theme when that changes: Windows' own, or the owner's choice.
pub fn follow(window: &Window, theme: Theme) {
    let app = window.app_handle();
    if let Some(window) = app.get_webview_window(window.label()) {
        let _ = window.set_background_color(Some(window_colour(saved_scheme(app), theme)));
    }
}

/// The look chosen.
#[tauri::command]
pub fn look(app: AppHandle) -> Result<Look, String> {
    Ok(saved(&app))
}

/// Chooses the look: from now, and at every start.
#[tauri::command]
pub fn set_look(app: AppHandle, look: Look) -> Result<Look, String> {
    let window = app.get_webview_window("main");
    show_then_keep(
        look,
        saved(&app),
        |look| match &window {
            Some(window) => window
                .set_theme(look.theme())
                .map_err(|error| format!("Windows didn't take that ({error}).")),
            None => Ok(()),
        },
        |look| keep(&app, LOOK, look),
    )
}

/// The scheme chosen.
#[tauri::command]
pub fn scheme(app: AppHandle) -> Result<Scheme, String> {
    Ok(saved_scheme(&app))
}

/// Chooses the scheme: from now (the page puts it on itself, and the window's colour under the
/// page follows), and at every start.
#[tauri::command]
pub fn set_scheme(app: AppHandle, scheme: Scheme) -> Result<Scheme, String> {
    let window = app.get_webview_window("main");
    show_then_keep(
        scheme,
        saved_scheme(&app),
        |scheme| match &window {
            Some(window) => {
                let theme = window.theme().map_err(|error| error.to_string())?;
                window
                    .set_background_color(Some(window_colour(scheme, theme)))
                    .map_err(|error| error.to_string())
            }
            None => Ok(()),
        },
        |scheme| keep(&app, SCHEME, scheme),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::cell::RefCell;

    #[test]
    fn the_look_reads_as_the_page_writes_it() {
        for (look, word) in [
            (Look::Windows, "windows"),
            (Look::Light, "light"),
            (Look::Dark, "dark"),
        ] {
            assert_eq!(serde_json::to_value(look).unwrap(), json!(word));
            assert_eq!(serde_json::from_value::<Look>(json!(word)).unwrap(), look);
        }
    }

    #[test]
    fn same_as_windows_gives_the_window_no_theme_of_its_own() {
        assert_eq!(Look::Windows.theme(), None);
        assert_eq!(Look::Light.theme(), Some(Theme::Light));
        assert_eq!(Look::Dark.theme(), Some(Theme::Dark));
        assert_eq!(Look::default(), Look::Windows);
    }

    #[test]
    fn the_scheme_reads_as_the_page_writes_it() {
        for scheme in [
            Scheme::Velvet,
            Scheme::Lagoon,
            Scheme::Dusk,
            Scheme::Graphite,
        ] {
            let word = scheme.word();
            assert_eq!(serde_json::to_value(scheme).unwrap(), json!(word));
            assert_eq!(
                serde_json::from_value::<Scheme>(json!(word)).unwrap(),
                scheme
            );
        }
        assert_eq!(Scheme::default(), Scheme::Velvet);
    }

    #[test]
    fn the_window_is_the_colour_of_the_page() {
        assert_eq!(
            window_colour(Scheme::Velvet, Theme::Light),
            Color(0xf6, 0xef, 0xea, 0xff)
        );
        assert_eq!(
            window_colour(Scheme::Velvet, Theme::Dark),
            Color(0x12, 0x0b, 0x0e, 0xff)
        );
        assert_eq!(
            window_colour(Scheme::Graphite, Theme::Dark),
            Color(0x0d, 0x0e, 0x10, 0xff)
        );
    }

    #[test]
    fn the_page_is_told_its_scheme_and_wears_it_before_its_first_frame() {
        let script = scheme_script(Scheme::Dusk);
        assert!(script.starts_with("window.__MAKU_SCHEME__ = \"dusk\";\n"));
        // Then the page's own script puts it on <html>, or the newer one a reload finds in the
        // session (app/src/lib/scheme-script.js, whose tests run it).
        assert!(script.ends_with(PAGE_SCRIPT));
        assert!(PAGE_SCRIPT.contains("document.documentElement"));
        assert!(PAGE_SCRIPT.contains("sessionStorage"));
    }

    /// What `show_then_keep` did, in order.
    fn steps() -> RefCell<Vec<String>> {
        RefCell::new(Vec::new())
    }

    #[test]
    fn a_choice_is_shown_on_the_window_before_it_is_kept() {
        let done = steps();
        let chosen = show_then_keep(
            Scheme::Dusk,
            Scheme::Velvet,
            |scheme| {
                done.borrow_mut().push(format!("show {scheme:?}"));
                Ok(())
            },
            |scheme| {
                done.borrow_mut().push(format!("keep {scheme:?}"));
                Ok(())
            },
        );
        assert_eq!(chosen, Ok(Scheme::Dusk));
        assert_eq!(*done.borrow(), ["show Dusk", "keep Dusk"]);
    }

    #[test]
    fn a_choice_the_window_does_not_take_is_not_kept() {
        let done = steps();
        let chosen = show_then_keep(
            Look::Light,
            Look::Windows,
            |_| Err("Windows didn't take that.".to_string()),
            |look| {
                done.borrow_mut().push(format!("keep {look:?}"));
                Ok(())
            },
        );
        assert_eq!(chosen, Err("Windows didn't take that.".to_string()));
        assert!(done.borrow().is_empty()); // the next start is as this one was
    }

    #[test]
    fn a_choice_that_cannot_be_kept_comes_off_the_window_again() {
        let done = steps();
        let chosen = show_then_keep(
            Scheme::Dusk,
            Scheme::Velvet,
            |scheme| {
                done.borrow_mut().push(format!("show {scheme:?}"));
                Ok(())
            },
            |_| Err("The disk is full.".to_string()),
        );
        assert_eq!(chosen, Err("The disk is full.".to_string()));
        assert_eq!(*done.borrow(), ["show Dusk", "show Velvet"]);
    }
}

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

/// What the page reads before anything else runs: the scheme, to take before its first frame
/// (app/src/main.tsx).
fn scheme_script(scheme: Scheme) -> String {
    format!("window.__MAKU_SCHEME__ = \"{}\";", scheme.word())
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
    let value = serde_json::to_value(look).map_err(|error| error.to_string())?;
    choices::save(&app, LOOK, value)?;
    if let Some(window) = app.get_webview_window("main") {
        window
            .set_theme(look.theme())
            .map_err(|error| format!("Windows didn't take that ({error})."))?;
    }
    Ok(look)
}

/// The scheme chosen.
#[tauri::command]
pub fn scheme(app: AppHandle) -> Result<Scheme, String> {
    Ok(saved_scheme(&app))
}

/// Chooses the scheme: from now (the page puts it on itself), and at every start.
#[tauri::command]
pub fn set_scheme(app: AppHandle, scheme: Scheme) -> Result<Scheme, String> {
    let value = serde_json::to_value(scheme).map_err(|error| error.to_string())?;
    choices::save(&app, SCHEME, value)?;
    if let Some(window) = app.get_webview_window("main") {
        let theme = window.theme().map_err(|error| error.to_string())?;
        window
            .set_background_color(Some(window_colour(scheme, theme)))
            .map_err(|error| error.to_string())?;
    }
    Ok(scheme)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

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
    fn the_page_is_told_its_scheme_and_nothing_else() {
        assert_eq!(
            scheme_script(Scheme::Dusk),
            "window.__MAKU_SCHEME__ = \"dusk\";"
        );
    }
}

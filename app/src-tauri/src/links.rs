//! Pages Maku opens in the browser. The window can't open addresses itself: it asks for one of
//! these by name, so it can never be steered anywhere else.

use tauri::AppHandle;
use tauri_plugin_opener::OpenerExt;

/// Every released version, newest first, with what changed and its installer.
/// Built by scripts/downloads-page.mjs; see docs/releasing.md.
pub const DOWNLOADS_PAGE: &str = "https://frankgrobbelaar.github.io/maku/";

/// Where a TMDB account's keys are, for the TMDB key in Setup.
pub const TMDB_API_PAGE: &str = "https://www.themoviedb.org/settings/api";

/// Opens the downloads page in the default browser.
#[tauri::command]
pub fn open_downloads_page(app: AppHandle) -> Result<(), String> {
    open(&app, DOWNLOADS_PAGE)
}

/// Opens TMDB's page with the account's API keys in the default browser.
#[tauri::command]
pub fn open_tmdb_api_page(app: AppHandle) -> Result<(), String> {
    open(&app, TMDB_API_PAGE)
}

/// Opens a show's or a film's page on TMDB ("tv" or "movie"), by its number there.
#[tauri::command]
pub fn open_tmdb_page(app: AppHandle, kind: String, id: u64) -> Result<(), String> {
    open(&app, &tmdb_page(&kind, id)?)
}

/// A show's or a film's page on TMDB: only its kind, one of two words, and a number go in.
fn tmdb_page(kind: &str, id: u64) -> Result<String, String> {
    match kind {
        "tv" | "movie" => Ok(format!("https://www.themoviedb.org/{kind}/{id}")),
        _ => Err(format!("TMDB has no pages of kind {kind:?}")),
    }
}

fn open(app: &AppHandle, address: &str) -> Result<(), String> {
    app.opener()
        .open_url(address, None::<&str>)
        .map_err(|error| error.to_string())
}

#[cfg(test)]
mod tests {
    use super::{DOWNLOADS_PAGE, TMDB_API_PAGE, tmdb_page};

    #[test]
    fn the_downloads_page_is_makus_own_secure_site() {
        assert!(DOWNLOADS_PAGE.starts_with("https://frankgrobbelaar.github.io/maku"));
    }

    #[test]
    fn the_tmdb_page_is_tmdbs_own_secure_site() {
        assert!(TMDB_API_PAGE.starts_with("https://www.themoviedb.org/"));
    }

    #[test]
    fn a_show_or_film_opens_on_tmdb_and_nothing_else_does() {
        assert_eq!(
            tmdb_page("tv", 4101).as_deref(),
            Ok("https://www.themoviedb.org/tv/4101")
        );
        assert_eq!(
            tmdb_page("movie", 7101).as_deref(),
            Ok("https://www.themoviedb.org/movie/7101")
        );
        assert!(tmdb_page("../settings", 1).is_err());
    }
}

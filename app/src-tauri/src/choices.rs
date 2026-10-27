//! The shell's own choices, kept in `window.json` in its own folder
//! (%LOCALAPPDATA%\io.github.frankgrobbelaar.maku), which uninstalling removes when Maku's data
//! goes too: whether closing the window keeps Maku in the tray, and whether it's light or dark.

use std::path::PathBuf;

use serde_json::{Map, Value};
use tauri::{AppHandle, Manager};

/// A choice, if it was ever made.
pub fn read(app: &AppHandle, key: &str) -> Option<Value> {
    let text = std::fs::read_to_string(file(app).ok()?).ok()?;
    choice_in(&text, key)
}

/// Keeps a choice, and the others as they were.
pub fn save(app: &AppHandle, key: &str, value: Value) -> Result<(), String> {
    let file = file(app)?;
    let before = std::fs::read_to_string(&file).unwrap_or_default();
    let write = || -> std::io::Result<()> {
        if let Some(folder) = file.parent() {
            std::fs::create_dir_all(folder)?;
        }
        std::fs::write(&file, with_choice(&before, key, value))
    };
    write().map_err(|error| format!("Maku couldn't keep that ({error})."))
}

fn file(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_local_data_dir()
        .map(|folder| folder.join("window.json"))
        .map_err(|error| format!("Maku couldn't find its own folder ({error})."))
}

/// The choice the file holds under `key`, if it holds one.
fn choice_in(text: &str, key: &str) -> Option<Value> {
    serde_json::from_str::<Map<String, Value>>(text)
        .ok()?
        .remove(key)
}

/// The file with `key` set to `value`. The other choices stay; a file that isn't Maku's choices
/// starts again.
fn with_choice(text: &str, key: &str, value: Value) -> String {
    let mut choices = serde_json::from_str::<Map<String, Value>>(text).unwrap_or_default();
    choices.insert(key.to_owned(), value);
    Value::Object(choices).to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn each_choice_keeps_its_own_place() {
        let text = with_choice("", "keepInTray", json!(true));
        let text = with_choice(&text, "look", json!("light"));
        let text = with_choice(&text, "keepInTray", json!(false));
        assert_eq!(choice_in(&text, "keepInTray"), Some(json!(false)));
        assert_eq!(choice_in(&text, "look"), Some(json!("light")));
    }

    #[test]
    fn a_choice_never_made_is_none() {
        assert_eq!(choice_in("", "look"), None);
        assert_eq!(choice_in("not json", "look"), None);
        assert_eq!(choice_in(r#"{"keepInTray": true}"#, "look"), None);
    }

    #[test]
    fn a_file_that_isnt_makus_choices_starts_again() {
        assert_eq!(
            with_choice("[1, 2]", "look", json!("dark")),
            r#"{"look":"dark"}"#
        );
    }
}

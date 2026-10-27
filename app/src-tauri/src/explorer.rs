//! Showing the owner's folders and files in Windows Explorer. The window names a path; the shell
//! only ever opens a folder, or shows a file selected in its folder, so nothing is run.

use std::path::Path;

use tauri::AppHandle;
use tauri_plugin_opener::OpenerExt;

/// Opens a folder in Explorer, such as a show's own folder.
#[tauri::command]
pub fn open_folder(app: AppHandle, path: String) -> Result<(), String> {
    let folder = existing_folder(&path)?;
    app.opener()
        .open_path(folder, None::<&str>)
        .map_err(|error| error.to_string())
}

/// Shows a file in Explorer, selected in its folder, such as a show's gap analysis.
#[tauri::command]
pub fn show_in_folder(app: AppHandle, path: String) -> Result<(), String> {
    let file = existing(&path)?;
    app.opener()
        .reveal_item_in_dir(file)
        .map_err(|error| error.to_string())
}

fn existing_folder(path: &str) -> Result<&str, String> {
    if Path::new(path).is_dir() {
        Ok(path)
    } else {
        Err(format!(
            "Windows can't open {path}: it isn't a folder that's there."
        ))
    }
}

fn existing(path: &str) -> Result<&str, String> {
    if Path::new(path).exists() {
        Ok(path)
    } else {
        Err(format!(
            "Windows can't show {path}: it isn't there any more."
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::{existing, existing_folder};

    #[test]
    fn only_a_folder_that_is_there_is_opened() {
        let here = env!("CARGO_MANIFEST_DIR");
        let file = concat!(env!("CARGO_MANIFEST_DIR"), "/Cargo.toml");
        assert_eq!(existing_folder(here), Ok(here));
        assert!(existing_folder(file).is_err()); // a file would be run, not shown
        assert!(existing_folder("Z:/nowhere/at/all").is_err());
    }

    #[test]
    fn a_file_is_shown_only_while_it_is_there() {
        let file = concat!(env!("CARGO_MANIFEST_DIR"), "/Cargo.toml");
        assert_eq!(existing(file), Ok(file));
        assert!(existing("Z:/nowhere/report.md").is_err());
    }
}

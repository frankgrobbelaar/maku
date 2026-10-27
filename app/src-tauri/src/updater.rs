//! Updates from Maku's GitHub releases.
//!
//! Every release carries latest.json, the update manifest. The updater reads the newest
//! one from the address in tauri.conf.json (`plugins.updater.endpoints`), downloads the
//! installer it names, and checks the installer's signature against the public key in the
//! same file before anything runs. See docs/releasing.md.

use std::sync::Mutex;

use serde::Serialize;
use tauri::{AppHandle, State};
use tauri_plugin_updater::{Error, Update, UpdaterExt};

use crate::engine::{self, Engine};

/// Mirrors `ReadyUpdate` in app/src/lib/updates.ts.
#[derive(Serialize)]
pub struct ReadyUpdate {
    version: String,
    /// What changed: the version's notes from CHANGELOG.md, carried by latest.json.
    notes: Option<String>,
}

/// An update that has been downloaded and is waiting for "Restart and update".
#[derive(Default)]
pub struct PendingUpdate(Mutex<Option<(Update, Vec<u8>)>>);

/// Checks for a newer Maku and downloads it. Returns `None` when Maku is up to date.
#[tauri::command]
pub async fn prepare_update(
    app: AppHandle,
    pending: State<'_, PendingUpdate>,
) -> Result<Option<ReadyUpdate>, String> {
    let update = match app.updater().map_err(text)?.check().await {
        Ok(Some(update)) => update,
        // GitHub answers 404 until the first release is published: nothing to update to.
        Ok(None) | Err(Error::ReleaseNotFound) => return Ok(None),
        Err(error) => return Err(text(error)),
    };

    let bytes = update.download(|_, _| {}, || {}).await.map_err(text)?;
    let ready = ReadyUpdate {
        version: update.version.clone(),
        notes: update.body.clone(),
    };
    *pending.0.lock().unwrap() = Some((update, bytes));
    Ok(Some(ready))
}

/// Stops the engine and runs the installer. Maku closes, and the installer opens it again.
/// If the installer can't start, the engine is started again so Maku keeps working.
#[tauri::command]
pub fn install_update(
    app: AppHandle,
    pending: State<'_, PendingUpdate>,
    engine: State<'_, Engine>,
) -> Result<(), String> {
    let (update, bytes) = pending
        .0
        .lock()
        .unwrap()
        .take()
        .ok_or("No update is ready to install.")?;
    engine.stop(); // the installer replaces the engine's files
    update.install(bytes).map_err(|error| {
        engine::start(app);
        text(error)
    })
}

fn text(error: impl std::fmt::Display) -> String {
    error.to_string()
}

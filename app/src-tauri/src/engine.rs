//! Starts Maku's engine (the Python program beside the window) and tells the UI
//! where to reach it.
//!
//! The handshake, also tested from the engine's side in engine/tests/test_cli.py:
//! - the shell starts `maku serve --watch-stdin` with a fresh token in MAKU_TOKEN;
//! - the engine prints one JSON line once it listens: {"event":"ready","port":N};
//! - before that, while a long job keeps it starting (moving the data to another drive), it
//!   prints {"event":"working"} every few seconds, and the shell waits on: it gives up only on
//!   an engine silent for a minute;
//! - the engine stops by itself when its stdin closes, so it never outlives the app;
//! - after the ready line, it may print {"event":"notify","title":…,"body":…,"link":…}:
//!   something worth telling the owner, a Windows notification while the window is away and a
//!   note in the window while it's open, `link` being where in Maku it leads (see tray.rs).
//!
//! If the engine stops on its own, before or after it was ready, the status becomes
//! `failed` with its last error lines, and the UI offers to try again. While the window is away
//! (Maku waiting in the tray), nobody sees that: Windows tells the owner once, and the shell tries
//! again by itself, after a pause that grows (the data's drive may not be there yet at sign-in).

use std::collections::VecDeque;
use std::io::{BufRead, BufReader, Read};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex, mpsc};
use std::thread;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, State};

use crate::{process, tray};

/// How long the engine may be silent while it starts. The first launch after an install is the
/// slowest; a long job at starting (moving the data) says it's still working as it goes.
const START_TIMEOUT: Duration = Duration::from_secs(60);
/// How many of the engine's last error lines to keep for "Copy details".
const ERROR_LINES: usize = 40;
/// Pauses before trying a failed engine again while the window is away, the last repeating.
const RETRY_PAUSES: [Duration; 4] = [
    Duration::from_secs(30),
    Duration::from_secs(60),
    Duration::from_secs(5 * 60),
    Duration::from_secs(15 * 60),
];
/// How long an engine must run before ending counts as stopping, not as failing to start.
const STAYED_UP: Duration = Duration::from_secs(120);
/// The longest line of the engine's own that a notification carries.
const SAID_AT_MOST: usize = 200;

/// What the UI sees. Mirrors `EngineStatus` in app/src/lib/engine.tsx.
#[derive(Clone, Default, Serialize)]
#[serde(tag = "state", rename_all = "camelCase")]
pub enum EngineStatus {
    #[default]
    Starting,
    Ready {
        url: String,
        token: String,
    },
    Failed {
        message: String,
        details: String,
    },
}

#[derive(Default)]
pub struct Engine {
    status: Mutex<EngineStatus>,
    running: Mutex<Option<Running>>,
}

struct Running {
    child: Child,
    /// Dropping this closes the pipe, which tells the engine to stop.
    stdin: ChildStdin,
}

impl Engine {
    /// Asks the engine to stop by closing its stdin, and ends it if it is still running after 3 seconds.
    pub fn stop(&self) {
        let Some(Running { mut child, stdin }) = self.running.lock().unwrap().take() else {
            return;
        };
        drop(stdin);
        for _ in 0..30 {
            if matches!(child.try_wait(), Ok(Some(_))) {
                return;
            }
            thread::sleep(Duration::from_millis(100));
        }
        let _ = child.kill();
        let _ = child.wait();
    }

    /// Called once an engine has exited. If it was still the current engine, nobody stopped
    /// it on purpose: it crashed. Either way, it is forgotten.
    fn ended_unexpectedly(&self, pid: u32) -> bool {
        let mut running = self.running.lock().unwrap();
        match running.take_if(|engine| engine.child.id() == pid) {
            Some(mut engine) => {
                let _ = engine.child.wait();
                true
            }
            None => false,
        }
    }
}

/// Starts the engine in the background. The UI follows along through `engine-status` events.
pub fn start(app: AppHandle) {
    run(app, 0);
}

/// Starts the engine, `failures` being how many tries in a row have failed before this one.
fn run(app: AppHandle, failures: usize) {
    set_status(&app, EngineStatus::Starting);
    thread::spawn(move || {
        let started = match launch(&app) {
            Ok(started) => started,
            Err(failure) => return fail(&app, failure, failures),
        };
        set_status(
            &app,
            EngineStatus::Ready {
                url: started.url,
                token: started.token,
            },
        );
        let ready_at = Instant::now();

        let _ = started.exited.recv(); // returns once the engine has exited
        if app.state::<Engine>().ended_unexpectedly(started.pid) {
            let failure = failed("It stopped unexpectedly.", started.errors.text());
            fail(&app, failure, failed_before(ready_at.elapsed(), failures));
        }
    });
}

/// A failed engine: the UI says so. While the window is away, Windows tells the owner (once in a
/// run of failures), and the engine is tried again after a pause, unless the owner has started it
/// since or has the window open (where "Try again" is theirs).
fn fail(app: &AppHandle, failure: EngineStatus, failures: usize) {
    if failures == 0
        && let EngineStatus::Failed { message, details } = &failure
    {
        let said = last_said(details).unwrap_or(message);
        tray::tell_away(
            app,
            "Maku isn't running",
            &format!("{said} Maku tries again by itself."),
        );
    }
    set_status(app, failure);
    let app = app.clone();
    thread::spawn(move || {
        loop {
            thread::sleep(pause_after(failures));
            if !matches!(
                *app.state::<Engine>().status.lock().unwrap(),
                EngineStatus::Failed { .. }
            ) {
                return; // started again meanwhile
            }
            if !tray::window_open(&app) && try_again(&app) {
                return run(app, failures + 1);
            }
        }
    });
}

/// The tries in a row that failed before this one, an engine having ended `ran_for` after it was
/// ready: one that ran a while starts a new count, but one that ended soon after (it couldn't
/// start after all: its records damaged, say) goes on with it, so the pauses keep growing and
/// Windows says so only once.
fn failed_before(ran_for: Duration, failures: usize) -> usize {
    if ran_for < STAYED_UP { failures } else { 0 }
}

/// How long to wait before trying again after this many failures in a row (0 for the first).
fn pause_after(failures: usize) -> Duration {
    RETRY_PAUSES[failures.min(RETRY_PAUSES.len() - 1)]
}

/// The engine's last line, when it's a short sentence of its own ("Maku's data is in F:\Maku,
/// which isn't there. Connect its drive, then try again.") rather than a crash's.
fn last_said(details: &str) -> Option<&str> {
    let line = details
        .lines()
        .map(str::trim)
        .rfind(|line| !line.is_empty())?;
    let sentence = line.len() <= SAID_AT_MOST && line.ends_with('.') && !line.contains("Error:");
    sentence.then_some(line)
}

/// Marks a failed engine as starting again, unless something else has (the owner pressing
/// "Try again"). True when it's this caller's to start.
fn try_again(app: &AppHandle) -> bool {
    let engine = app.state::<Engine>();
    let mut status = engine.status.lock().unwrap();
    if !matches!(*status, EngineStatus::Failed { .. }) {
        return false;
    }
    *status = EngineStatus::Starting;
    true
}

#[tauri::command]
pub fn engine_status(engine: State<'_, Engine>) -> EngineStatus {
    engine.status.lock().unwrap().clone()
}

/// Tries again after a failure. Does nothing while the engine is already starting.
#[tauri::command]
pub fn restart_engine(app: AppHandle, engine: State<'_, Engine>) {
    {
        let mut status = engine.status.lock().unwrap();
        if matches!(*status, EngineStatus::Starting) {
            return;
        }
        *status = EngineStatus::Starting;
    }
    engine.stop();
    start(app);
}

/// A started engine, and what it takes to notice if it stops on its own.
struct Started {
    url: String,
    token: String,
    pid: u32,
    /// `recv()` on this returns once the engine's output closes, which is when it exits.
    exited: mpsc::Receiver<Starting>,
    errors: ErrorLog,
}

fn launch(app: &AppHandle) -> Result<Started, EngineStatus> {
    let mut command = engine_command(app).map_err(|message| failed(message, String::new()))?;
    let token = new_token();
    command
        .args(["serve", "--watch-stdin"])
        .env("MAKU_TOKEN", &token)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let mut child = command.spawn().map_err(|error| {
        // Name the program, but not the environment: it holds the token.
        let program = command.get_program().to_string_lossy().into_owned();
        failed(format!("Windows couldn't run it ({error})."), program)
    })?;
    let pid = child.id();
    let stdin = child.stdin.take().expect("stdin is piped");
    let errors = ErrorLog::follow(child.stderr.take().expect("stderr is piped"));

    let told = app.clone();
    let stdout = child.stdout.take().expect("stdout is piped");
    let heard =
        move |title: &str, body: &str, link: Option<&str>| tray::tell(&told, title, body, link);
    match wait_for_port(stdout, START_TIMEOUT, heard) {
        Ok((port, exited)) => {
            *app.state::<Engine>().running.lock().unwrap() = Some(Running { child, stdin });
            Ok(Started {
                url: format!("http://127.0.0.1:{port}"),
                token,
                pid,
                exited,
                errors,
            })
        }
        Err(problem) => {
            let _ = child.kill();
            let _ = child.wait();
            let message = match problem {
                NotReady::TimedOut => "It didn't answer within a minute.",
                NotReady::Exited => "It stopped before it was ready.",
            };
            Err(failed(message, errors.text()))
        }
    }
}

/// In development the engine runs from source with uv, keeping its data in
/// engine/.dev-data so development never touches the real data in %LOCALAPPDATA%\Maku.
/// Installed, it is the bundled maku-engine.exe.
fn engine_command(app: &AppHandle) -> Result<Command, String> {
    if cfg!(debug_assertions) {
        let source = concat!(env!("CARGO_MANIFEST_DIR"), "/../../engine");
        let mut command = process::hidden("uv");
        command.args(["run", "--project", source, "maku"]);
        if std::env::var_os("MAKU_DATA_DIR").is_none() {
            command.env("MAKU_DATA_DIR", format!("{source}/.dev-data"));
        }
        Ok(command)
    } else {
        let resources = app
            .path()
            .resource_dir()
            .map_err(|error| format!("Maku couldn't find its own files ({error})."))?;
        Ok(process::hidden(
            resources.join("engine").join("maku-engine.exe"),
        ))
    }
}

/// A fresh secret for every launch, so only this window can talk to this engine.
fn new_token() -> String {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).expect("Windows always provides random bytes");
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

#[derive(Debug)]
enum NotReady {
    TimedOut,
    Exited,
}

/// What the engine says on its stdout, one JSON object a line.
#[derive(Deserialize)]
#[serde(tag = "event", rename_all = "lowercase")]
enum Said {
    /// It listens on this port.
    Ready { port: u16 },
    /// Still starting: a long job (moving the data) is under way.
    Working,
    /// Something worth telling the owner, and where in Maku it leads.
    Notify {
        title: String,
        body: String,
        #[serde(default)]
        link: Option<String>,
    },
}

/// What the reader passes on while the engine starts.
enum Starting {
    Ready(u16),
    Working,
}

/// Reads the engine's stdout until it announces its port, waiting on while it says it's still
/// working, and giving up once it's silent for `patience`. Reading carries on, passing what it
/// tells after that to `heard` (a title, a line and a link) and the rest by, so the engine never stalls
/// on a full pipe, until the engine exits and its output closes; that is when `recv()` on the
/// returned receiver comes back.
fn wait_for_port(
    stdout: impl Read + Send + 'static,
    patience: Duration,
    heard: impl Fn(&str, &str, Option<&str>) + Send + 'static,
) -> Result<(u16, mpsc::Receiver<Starting>), NotReady> {
    let (announce, announced) = mpsc::channel();
    thread::spawn(move || {
        let mut ready = false;
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            match serde_json::from_str(&line) {
                Ok(Said::Ready { port }) if !ready => {
                    ready = true;
                    let _ = announce.send(Starting::Ready(port));
                }
                Ok(Said::Working) if !ready => {
                    let _ = announce.send(Starting::Working);
                }
                Ok(Said::Notify { title, body, link }) if ready => {
                    heard(&title, &body, link.as_deref());
                }
                _ => {}
            }
        }
    });
    loop {
        match announced.recv_timeout(patience) {
            Ok(Starting::Ready(port)) => return Ok((port, announced)),
            Ok(Starting::Working) => {}
            Err(mpsc::RecvTimeoutError::Timeout) => return Err(NotReady::TimedOut),
            Err(mpsc::RecvTimeoutError::Disconnected) => return Err(NotReady::Exited),
        }
    }
}

/// The engine's last few stderr lines, for the failure report.
struct ErrorLog {
    lines: Arc<Mutex<VecDeque<String>>>,
    finished: mpsc::Receiver<()>,
}

impl ErrorLog {
    fn follow(stderr: impl Read + Send + 'static) -> Self {
        let lines = Arc::new(Mutex::new(VecDeque::with_capacity(ERROR_LINES)));
        let (done, finished) = mpsc::channel();
        let kept = Arc::clone(&lines);
        thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                let mut kept = kept.lock().unwrap();
                if kept.len() == ERROR_LINES {
                    kept.pop_front();
                }
                kept.push_back(line);
            }
            let _ = done.send(());
        });
        Self { lines, finished }
    }

    /// Everything kept so far, after giving the engine a moment to finish writing.
    fn text(&self) -> String {
        let _ = self.finished.recv_timeout(Duration::from_secs(1));
        let lines = self.lines.lock().unwrap();
        lines.iter().cloned().collect::<Vec<_>>().join("\n")
    }
}

fn set_status(app: &AppHandle, status: EngineStatus) {
    *app.state::<Engine>().status.lock().unwrap() = status.clone();
    let _ = app.emit("engine-status", status);
}

fn failed(message: impl Into<String>, details: String) -> EngineStatus {
    EngineStatus::Failed {
        message: message.into(),
        details,
    }
}

#[cfg(test)]
mod tests {
    use std::io::Cursor;

    use super::*;

    const READY: &str = "{\"event\":\"ready\",\"port\":51234}\n";

    const WORKING: &str = "{\"event\":\"working\"}\n";

    #[test]
    fn finds_the_port_in_the_ready_line() {
        let stdout = Cursor::new(format!("starting\n{READY}"));
        assert!(matches!(
            wait_for_port(stdout, START_TIMEOUT, |_, _, _| {}),
            Ok((51234, _))
        ));
    }

    #[test]
    fn notices_when_the_engine_exits_without_announcing_a_port() {
        let stdout = Cursor::new("Traceback (most recent call last):\n");
        assert!(matches!(
            wait_for_port(stdout, START_TIMEOUT, |_, _, _| {}),
            Err(NotReady::Exited)
        ));
    }

    /// An engine's output, each line after a pause.
    struct Slowly {
        lines: VecDeque<String>,
        pause: Duration,
    }

    impl Slowly {
        fn new(lines: &[&str], pause: Duration) -> Self {
            let lines = lines.iter().map(|line| line.to_string()).collect();
            Self { lines, pause }
        }
    }

    impl Read for Slowly {
        fn read(&mut self, buffer: &mut [u8]) -> std::io::Result<usize> {
            let Some(line) = self.lines.pop_front() else {
                return Ok(0);
            };
            thread::sleep(self.pause);
            buffer[..line.len()].copy_from_slice(line.as_bytes());
            Ok(line.len())
        }
    }

    #[test]
    fn waits_on_while_the_engine_says_it_is_still_working() {
        let pause = Duration::from_millis(60);
        let stdout = Slowly::new(&[WORKING, WORKING, WORKING, WORKING, READY], pause);
        let patience = Duration::from_millis(150); // less than it takes in all, more than a pause
        assert!(matches!(
            wait_for_port(stdout, patience, |_, _, _| {}),
            Ok((51234, _))
        ));
    }

    #[test]
    fn gives_up_on_an_engine_that_is_silent_too_long() {
        let stdout = Slowly::new(&[READY], Duration::from_millis(400));
        assert!(matches!(
            wait_for_port(stdout, Duration::from_millis(100), |_, _, _| {}),
            Err(NotReady::TimedOut)
        ));
    }

    #[test]
    fn passes_on_what_the_engine_tells_once_it_is_ready() {
        let notice = "{\"event\":\"notify\",\"title\":\"Quiet Hours is done\",\"body\":\"6 episodes\",\"link\":\"/titles/12\"}\n";
        let plain = "{\"event\":\"notify\",\"title\":\"Paused\",\"body\":\"No room\"}\n";
        let stdout = Cursor::new(format!("{notice}{READY}{notice}{plain}"));
        let (heard, hear) = mpsc::channel();
        let (_, exited) = wait_for_port(stdout, START_TIMEOUT, move |title, body, link| {
            let _ = heard.send(format!("{title}: {body} ({})", link.unwrap_or("-")));
        })
        .expect("a port");
        let _ = exited.recv(); // the engine's output is over
        assert_eq!(
            hear.try_iter().collect::<Vec<_>>(),
            [
                "Quiet Hours is done: 6 episodes (/titles/12)",
                "Paused: No room (-)"
            ]
        );
    }

    #[test]
    fn notices_when_the_engine_exits_after_starting() {
        let stdout = Cursor::new(format!("{READY}{READY}later output\n"));
        let (_, exited) = wait_for_port(stdout, START_TIMEOUT, |_, _, _| {}).expect("a port");
        assert!(
            exited.recv().is_err(),
            "only one announcement, then the end"
        );
    }

    #[test]
    fn keeps_only_the_last_error_lines() {
        let stderr: String = (1..=50).map(|n| format!("line {n}\n")).collect();
        let kept = ErrorLog::follow(Cursor::new(stderr)).text();
        assert!(kept.starts_with("line 11\n"));
        assert!(kept.ends_with("line 50"));
    }

    #[test]
    fn a_failed_engine_is_tried_again_after_a_growing_pause() {
        let pauses: Vec<u64> = (0..6).map(|n| pause_after(n).as_secs()).collect();
        assert_eq!(pauses, [30, 60, 300, 900, 900, 900]);
    }

    #[test]
    fn an_engine_ending_soon_after_it_was_ready_goes_on_with_the_failures() {
        assert_eq!(failed_before(Duration::from_secs(5), 3), 3);
        assert_eq!(failed_before(Duration::from_secs(600), 3), 0);
    }

    #[test]
    fn a_notification_carries_the_engines_own_sentence_not_a_crash() {
        let missing =
            "Maku's data is in F:\\Maku, which isn't there. Connect its drive, then try again.";
        assert_eq!(last_said(&format!("{missing}\n")), Some(missing));
        let crash = "Traceback (most recent call last):\n  File \"x.py\"\nValueError: bad.";
        assert_eq!(last_said(crash), None);
        assert_eq!(last_said(""), None);
    }

    #[test]
    fn every_launch_gets_a_new_long_token() {
        let (first, second) = (new_token(), new_token());
        assert_eq!(first.len(), 64);
        assert_ne!(first, second);
    }
}

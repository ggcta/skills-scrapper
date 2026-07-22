// Prevent an extra console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! SkillsScraper — a thin Tauri desktop shell over the validated
//! `skills-scraper` Go binary. Every operation shells out to it; the GUI never
//! reimplements scraping logic, so it inherits the CLI's verified behaviour.

use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, State};

/// A list/search row, matching `skills-scraper --json` output. The fetch-status
/// fields must be declared here or they'd be silently dropped on the round-trip
/// through this struct (serde ignores unknown fields on the way in and only
/// re-emits declared ones on the way out), leaving the GUI badges blank.
#[derive(Serialize, serde::Deserialize)]
struct Item {
    id: String,
    name: String,
    #[serde(rename = "type")]
    kind: String,
    portal: String,
    #[serde(default)]
    fetched: bool,
    #[serde(default, rename = "scrapedTime")]
    scraped_time: i64,
    #[serde(default, rename = "scrapedDate")]
    scraped_date: String,
}

/// Holds the running `skills-scraper browser` child — the persistent, reusable
/// browser (backlog #13). It stays open across fetch/sync tasks (which connect to
/// it) until close_browser or the window-close teardown ends it. Deliberately NOT
/// behind BrowserGuard: fetches are meant to run WHILE it is open and reuse it.
struct BrowserSession(Mutex<Option<Child>>);

/// Single-flight guard: only ONE browser-driving op (sync / fetch / login
/// session) may run at a time, because they all share the one persistent Chrome
/// profile (.webdriver_profiles) and a second concurrent Chrome collides on its
/// SingletonLock. Try-acquire semantics → a second attempt is rejected, not
/// queued (KISS). An owned Arc clone can be moved into a background thread so the
/// guard is released when the work truly finishes (e.g. a login session spans
/// two commands, so no held MutexGuard could bridge it).
#[derive(Clone)]
struct BrowserGuard(Arc<AtomicBool>);

impl BrowserGuard {
    /// Returns true if the guard was free and is now held by the caller.
    fn try_acquire(&self) -> bool {
        self.0
            .compare_exchange(false, true, Ordering::Acquire, Ordering::Relaxed)
            .is_ok()
    }
    fn release(&self) {
        self.0.store(false, Ordering::Release);
    }
}

const BUSY_MSG: &str = "A browser task is already running — wait for it to finish.";

/// Tracks the PID of the running browser-driving subprocess (a `fetch` or a
/// `sync`, if any) so `stop_fetch` and the window-close teardown can signal it.
/// Cleared as soon as the subprocess is reaped. Single-flight (BrowserGuard)
/// guarantees at most one at a time.
#[derive(Clone)]
struct FetchState(Arc<Mutex<Option<u32>>>);

/// Holds the running fetch's stdin so `continue_fetch` can send a newline when
/// the binary asks for sign-in (@@AUTH_REQUIRED), letting the user log in in the
/// visible browser and resume the same session. Cleared when the fetch ends.
#[derive(Clone)]
struct FetchStdin(Arc<Mutex<Option<std::process::ChildStdin>>>);

/// Candidate directories to search for the repo root / skills-scraper binary: an explicit
/// CSB_PROJECT_ROOT, then every ancestor of the working dir, then every ancestor
/// of the app executable (so it works no matter where the app is launched from).
fn candidate_roots() -> Vec<PathBuf> {
    let mut roots = Vec::new();
    if let Ok(p) = std::env::var("CSB_PROJECT_ROOT") {
        roots.push(PathBuf::from(p));
    }
    if let Ok(cwd) = std::env::current_dir() {
        roots.extend(cwd.ancestors().map(|a| a.to_path_buf()));
    }
    if let Ok(exe) = std::env::current_exe() {
        roots.extend(exe.ancestors().map(|a| a.to_path_buf()));
    }
    roots
}

/// Resolve the `skills-scraper` binary. Prefers CSB_BIN, else the first candidate
/// root that contains a known binary name. Returns an actionable error if none is
/// found. Legacy names (csb.bin / csb) are still accepted so old local builds keep
/// working after the rebrand.
fn resolve_csb() -> Result<PathBuf, String> {
    if let Ok(b) = std::env::var("CSB_BIN") {
        let p = PathBuf::from(&b);
        if p.exists() {
            return Ok(p);
        }
        return Err(format!("CSB_BIN points to a missing file: {b}"));
    }
    // Prefer the extensioned build artifact (skills-scraper.bin / .exe on
    // Windows); legacy csb.bin / csb names are still honoured for old builds.
    let names: &[&str] = if cfg!(windows) {
        &["skills-scraper.exe", "skills-scraper.bin", "csb.exe", "csb.bin", "csb"]
    } else {
        &["skills-scraper.bin", "skills-scraper", "csb.bin", "csb"]
    };
    for r in candidate_roots() {
        for name in names {
            let c = r.join(name);
            if c.exists() {
                return Ok(c);
            }
        }
    }
    Err("skills-scraper binary not found. Build it from the repo root:\n  \
         cd go && go build -o ../skills-scraper.bin .\n\
         (or run `just cli`, or set CSB_BIN to its full path)."
        .to_string())
}

/// The repository root (where data/ and csbmdvault/ live), used as the working
/// directory for csb. Prefers a checkout containing both `.git` and `go`, else
/// the directory holding the resolved skills-scraper binary.
fn repo_root() -> PathBuf {
    for r in candidate_roots() {
        if r.join(".git").exists() && r.join("go").exists() {
            return r;
        }
    }
    if let Ok(csb) = resolve_csb() {
        if let Some(parent) = csb.parent() {
            return parent.to_path_buf();
        }
    }
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

fn portal_flag(portal: &str) -> &'static str {
    if portal == "partner" {
        "-B"
    } else {
        "-A"
    }
}

fn kind_flag(kind: &str, long: bool) -> &'static str {
    match (kind, long) {
        ("courses", true) | ("course", true) => "--courses",
        ("labs", true) | ("lab", true) => "--labs",
        ("paths", true) | ("path", true) => "--paths",
        ("courses", false) | ("course", false) => "-c",
        ("labs", false) | ("lab", false) => "-l",
        _ => "-p",
    }
}

/// Build the `fetch` argv for the binary from the Fetch-tab inputs. Extracted so
/// the id/all handling is unit-tested.
///
/// The frontend already splits the "IDs or URLs" box on spaces/commas into a
/// list. Two things the binary needs:
///   - "all" (any case) means bulk-fetch the whole catalog for the selected type,
///     which the binary exposes as `--all <type>` (not an id).
///   - otherwise the ids must be ONE comma-joined value, because the binary's
///     -p/-c/-l flag consumes a single token (which it then splits on comma/
///     space). Passing them as separate args would drop all but the first.
fn fetch_args(
    portal: &str,
    kind: &str,
    ids: &[String],
    force: bool,
    signin: bool,
    toc: bool,
    no_transcript: bool,
    headless: bool,
) -> Vec<String> {
    let mut args: Vec<String> = vec!["fetch".into(), portal_flag(portal).into()];

    let cleaned: Vec<String> = ids
        .iter()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect();
    if cleaned.iter().any(|s| s.eq_ignore_ascii_case("all")) {
        // Bulk mode for the selected type: --all paths|courses|labs.
        args.push("--all".into());
        args.push(kind_flag(kind, true).trim_start_matches('-').to_string());
    } else {
        args.push(kind_flag(kind, false).into());
        args.push(cleaned.join(","));
    }

    if force {
        args.push("--force".into());
    }
    // #11: open the sign-in page and wait (the fetch-auth-required event drives
    // the modal; Continue answers it via continue_fetch).
    if signin {
        args.push("--signin".into());
    }
    if toc {
        args.push("--toc".into());
    }
    // #12: transcripts are always fetched into the JSON; this only omits them from
    // the generated Markdown.
    if no_transcript {
        args.push("--md-no-transcript".into());
    }
    if headless {
        args.push("--headless".into());
    }
    // Ask the binary for machine-readable "@@ITEM {json}" markers so we can
    // refresh the Browse badges live as each item is saved.
    args.push("--emit-progress".into());
    args
}

/// Run `csb` to completion and return stdout (used for the --json commands).
fn run_csb(args: &[String]) -> Result<String, String> {
    let bin = resolve_csb()?;
    let out = Command::new(&bin)
        .args(args)
        .current_dir(repo_root())
        .envs(csb_env())
        .output()
        .map_err(|e| format!("failed to launch skills-scraper ({}): {e}", bin.display()))?;
    if !out.status.success() {
        return Err(String::from_utf8_lossy(&out.stderr).into_owned());
    }
    Ok(String::from_utf8_lossy(&out.stdout).into_owned())
}

/// Like run_csb but records the child PID into `pid` while it runs, so a
/// browser-driving call (Sync) can be SIGTERM'd by the window-close teardown
/// instead of orphaning Chrome. The PID is cleared as soon as the child is reaped.
fn run_csb_tracked(args: &[String], pid: &Arc<Mutex<Option<u32>>>) -> Result<String, String> {
    let bin = resolve_csb()?;
    let child = Command::new(&bin)
        .args(args)
        .current_dir(repo_root())
        .envs(csb_env())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("failed to launch skills-scraper ({}): {e}", bin.display()))?;
    *pid.lock().unwrap() = Some(child.id());
    let out = child.wait_with_output();
    *pid.lock().unwrap() = None; // cleared right after reaping, before PID reuse
    let out = out.map_err(|e| e.to_string())?;
    if !out.status.success() {
        return Err(String::from_utf8_lossy(&out.stderr).into_owned());
    }
    Ok(String::from_utf8_lossy(&out.stdout).into_owned())
}

// list_items reads the local database only (no browser), so it needs no guard —
// it's async purely to keep the blocking subprocess call off the UI thread.
#[tauri::command]
async fn list_items(portal: String, kind: String) -> Result<Vec<Item>, String> {
    let args = vec![
        "list".into(),
        portal_flag(&portal).into(),
        kind_flag(&kind, true).into(),
        "--json".into(),
    ];
    let out = tauri::async_runtime::spawn_blocking(move || run_csb(&args))
        .await
        .map_err(|e| format!("list task failed: {e}"))??;
    serde_json::from_str(&out).map_err(|e| e.to_string())
}

/// Refresh the catalog (paths/courses/labs) from the website, then return the
/// stored list. Runs `skills-scraper list --reload --headless --json`, which opens a
/// headless browser and pages through the site's catalog API. This is the only
/// way to populate an empty first-run database, so the GUI exposes it as a
/// distinct "Sync" action (slower than the local-only Refresh).
#[tauri::command]
async fn sync_items(
    guard: State<'_, BrowserGuard>,
    fetch_state: State<'_, FetchState>,
    portal: String,
    kind: String,
) -> Result<Vec<Item>, String> {
    // Browser op: hold the single-flight guard for the whole reload, and track
    // the child PID so a window close mid-sync tears Chrome down (backlog #1).
    let guard = guard.inner().clone();
    let fetch_state = fetch_state.inner().clone();
    if !guard.try_acquire() {
        return Err(BUSY_MSG.into());
    }
    let args = vec![
        "list".into(),
        portal_flag(&portal).into(),
        kind_flag(&kind, true).into(),
        "--reload".into(),
        "--headless".into(),
        "--json".into(),
    ];
    let joined =
        tauri::async_runtime::spawn_blocking(move || run_csb_tracked(&args, &fetch_state.0)).await;
    guard.release(); // release on every path, before propagating any error
    let out = joined.map_err(|e| format!("sync task failed: {e}"))??;
    serde_json::from_str(&out).map_err(|e| e.to_string())
}

// search_items reads the local database only (no browser), so no guard.
#[tauri::command]
async fn search_items(portal: String, query: String, kind: String) -> Result<Vec<Item>, String> {
    let mut args = vec!["search".into(), query, portal_flag(&portal).into()];
    if kind != "all" {
        // search uses the singular flags (--course/--path/--lab)
        let flag = match kind.as_str() {
            "courses" | "course" => "--course",
            "labs" | "lab" => "--lab",
            _ => "--path",
        };
        args.push(flag.into());
    }
    args.push("--json".into());
    let out = tauri::async_runtime::spawn_blocking(move || run_csb(&args))
        .await
        .map_err(|e| format!("search task failed: {e}"))??;
    serde_json::from_str(&out).map_err(|e| e.to_string())
}

/// Stream a `skills-scraper fetch` run, emitting each output line as a `fetch-log`
/// event, `@@ITEM` markers as `fetch-item`, and a final `fetch-done` (bool
/// success). The subprocess is spawned in-command (so a launch failure rejects
/// the invoke promise), then drained/waited on a background thread — the command
/// returns immediately so the UI never blocks. The browser guard is released when
/// the subprocess actually finishes, not at return.
#[tauri::command]
async fn fetch(
    app: AppHandle,
    guard: State<'_, BrowserGuard>,
    fetch_state: State<'_, FetchState>,
    fetch_stdin: State<'_, FetchStdin>,
    portal: String,
    kind: String,
    ids: Vec<String>,
    force: bool,
    signin: bool,
    toc: bool,
    no_transcript: bool,
    headless: bool,
) -> Result<(), String> {
    let guard = guard.inner().clone();
    let fetch_state = fetch_state.inner().clone();
    let fetch_stdin = fetch_stdin.inner().clone();
    if !guard.try_acquire() {
        return Err(BUSY_MSG.into());
    }

    let args = fetch_args(
        &portal,
        &kind,
        &ids,
        force,
        signin,
        toc,
        no_transcript,
        headless,
    );

    // Spawn in-command so a launch failure rejects the promise (and frees the
    // guard); release on every early-error path.
    let bin = match resolve_csb() {
        Ok(b) => b,
        Err(e) => {
            guard.release();
            return Err(e);
        }
    };
    let mut child = match Command::new(&bin)
        .args(&args)
        .current_dir(repo_root())
        .envs(csb_env())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(c) => c,
        Err(e) => {
            guard.release();
            return Err(format!(
                "failed to launch skills-scraper ({}): {e}",
                bin.display()
            ));
        }
    };

    // Record the PID so stop_fetch can signal it (Ctrl+C style), and the stdin so
    // continue_fetch can answer an @@AUTH_REQUIRED sign-in prompt.
    *fetch_state.0.lock().unwrap() = Some(child.id());
    *fetch_stdin.0.lock().unwrap() = child.stdin.take();

    // Forward stderr lines on their own thread (progress is printed there).
    if let Some(err) = child.stderr.take() {
        let app2 = app.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(err).lines().map_while(Result::ok) {
                let _ = app2.emit("fetch-log", line);
            }
        });
    }

    // Drain stdout, wait, signal done, and release the guard — all off the UI
    // thread. The command returns immediately below (fire-and-forget past spawn).
    std::thread::spawn(move || {
        if let Some(out) = child.stdout.take() {
            for line in BufReader::new(out).lines().map_while(Result::ok) {
                // Structured markers: @@ITEM → fetch-item (live badge), and
                // @@AUTH_REQUIRED → fetch-auth-required (prompt the user to sign
                // in in the visible browser, then continue_fetch). Everything else
                // is a normal console log line.
                if let Some(json) = line.strip_prefix("@@ITEM ") {
                    let _ = app.emit("fetch-item", json.to_string());
                } else if let Some(url) = line.strip_prefix("@@AUTH_REQUIRED ") {
                    let _ = app.emit("fetch-auth-required", url.to_string());
                } else {
                    let _ = app.emit("fetch-log", line);
                }
            }
        }
        let ok = child.wait().map(|s| s.success()).unwrap_or(false);
        // Clear the PID + stdin right after reaping, before anything can reuse them.
        *fetch_state.0.lock().unwrap() = None;
        *fetch_stdin.0.lock().unwrap() = None;
        let _ = app.emit("fetch-done", ok);
        guard.release(); // released when the browser op truly finishes
    });

    Ok(())
}

/// Send SIGTERM to a subprocess so the Go binary handles it gracefully (Ctrl+C
/// style: it closes Chrome and keeps already-saved items). No-op on non-unix.
fn sigterm(pid: u32) {
    #[cfg(unix)]
    unsafe {
        libc::kill(pid as libc::pid_t, libc::SIGTERM);
    }
    #[cfg(not(unix))]
    {
        let _ = pid;
    }
}

/// Stop the running fetch the way Ctrl+C does on the CLI. Completion still
/// arrives via `fetch-done`. No-op with a message if nothing is running.
#[tauri::command]
fn stop_fetch(fetch_state: State<FetchState>) -> Result<(), String> {
    match *fetch_state.0.lock().unwrap() {
        Some(pid) => {
            sigterm(pid);
            Ok(())
        }
        None => Err("No fetch is running.".into()),
    }
}

/// Answer a fetch's @@AUTH_REQUIRED prompt: write a newline to its stdin (the
/// user has signed in in the visible browser), so the binary reloads and resumes
/// the same session.
#[tauri::command]
fn continue_fetch(fetch_stdin: State<FetchStdin>) -> Result<(), String> {
    match fetch_stdin.0.lock().unwrap().as_mut() {
        Some(stdin) => stdin.write_all(b"\n").map_err(|e| e.to_string()),
        None => Err("No fetch is waiting for sign-in.".into()),
    }
}

/// Open the persistent, reusable browser (backlog #13): spawn `skills-scraper
/// browser`, which opens a visible Chrome, advertises a reuse endpoint, and stays
/// open. The user signs in / browses freely; later fetches connect to this same
/// Chrome. It does NOT take BrowserGuard — fetches are meant to run alongside it.
/// Rejects a second open while one is already running.
#[tauri::command]
fn open_browser(state: State<BrowserSession>, portal: String) -> Result<(), String> {
    let mut slot = state.0.lock().unwrap();
    if slot.is_some() {
        return Err("A browser is already open.".into());
    }
    let bin = resolve_csb()?;
    let child = Command::new(&bin)
        .args(["browser", portal_flag(&portal)])
        .current_dir(repo_root())
        .envs(csb_env())
        .stdin(Stdio::piped())
        .spawn()
        .map_err(|e| format!("failed to launch skills-scraper ({}): {e}", bin.display()))?;
    *slot = Some(child);
    Ok(())
}

/// Close the persistent browser: send a newline to its stdin so it clears the
/// reuse endpoint and shuts Chrome down gracefully, then wait — off the UI thread.
#[tauri::command]
async fn close_browser(state: State<'_, BrowserSession>) -> Result<(), String> {
    // Take the child out under the lock, then drop the MutexGuard before awaiting.
    let child_opt = state.0.lock().unwrap().take();
    if let Some(mut child) = child_opt {
        let _ = tauri::async_runtime::spawn_blocking(move || {
            if let Some(mut stdin) = child.stdin.take() {
                let _ = stdin.write_all(b"\n");
            }
            let _ = child.wait();
        })
        .await;
    }
    Ok(())
}

/// Report the reusable browser's state: "none", "alive" (a fetch will reuse it),
/// or "stale" (advertised but unresponsive — the GUI asks the user to close it).
/// Off the UI thread since it does a quick network probe via the binary.
#[tauri::command]
async fn browser_status() -> Result<String, String> {
    let out = tauri::async_runtime::spawn_blocking(|| run_csb(&["browser-status".into()]))
        .await
        .map_err(|e| format!("browser-status task failed: {e}"))??;
    Ok(out.trim().to_string())
}

/// Open a file or folder with the OS default handler.
fn os_open(path: &str) -> Result<(), String> {
    let opener = if cfg!(target_os = "macos") {
        "open"
    } else if cfg!(target_os = "windows") {
        "explorer"
    } else {
        "xdg-open"
    };
    Command::new(opener)
        .arg(path)
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(())
}

/// Reveal the Markdown vault in the OS file manager.
#[tauri::command]
fn open_vault() -> Result<(), String> {
    let vault = repo_root().join("csbmdvault");
    os_open(&vault.to_string_lossy())
}

/// Open a stored item's Markdown file in the OS default app. Resolves the path
/// via `skills-scraper mdpath`, so the GUI never reimplements the vault layout or
/// filename sanitization. Returns the binary's error (e.g. "not fetched yet…")
/// on failure, for the frontend to surface.
// open_md resolves a local path (mdpath) then opens it — no browser, no guard;
// async only to keep the blocking mdpath call off the UI thread.
#[tauri::command]
async fn open_md(portal: String, kind: String, id: String) -> Result<(), String> {
    let args = vec![
        "mdpath".into(),
        portal_flag(&portal).into(),
        kind_flag(&kind, false).into(),
        id,
    ];
    let path = tauri::async_runtime::spawn_blocking(move || run_csb(&args))
        .await
        .map_err(|e| format!("mdpath task failed: {e}"))??
        .trim()
        .to_string();
    if path.is_empty() {
        return Err("Markdown path not found.".into());
    }
    os_open(&path)
}

/// List available PDF theme names (backlog #5) for the Browse theme picker.
#[tauri::command]
async fn list_themes() -> Result<Vec<String>, String> {
    let out = tauri::async_runtime::spawn_blocking(|| {
        run_csb(&["pdf".into(), "--list-themes".into()])
    })
    .await
    .map_err(|e| format!("list-themes task failed: {e}"))??;
    Ok(out
        .lines()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect())
}

/// Like run_csb but keeps stdout even when the binary exits non-zero. `pdf
/// --doctor` reports "not ready" AND exits 1 (so it stays usable in a shell
/// conditional) — for the GUI that is a successful answer, not a failure.
fn run_csb_output(args: &[String]) -> Result<String, String> {
    let bin = resolve_csb()?;
    let out = Command::new(&bin)
        .args(args)
        .current_dir(repo_root())
        .envs(csb_env())
        .output()
        .map_err(|e| format!("failed to launch skills-scraper ({}): {e}", bin.display()))?;
    output_or_error(
        String::from_utf8_lossy(&out.stdout).into_owned(),
        String::from_utf8_lossy(&out.stderr).into_owned(),
    )
}

/// Which stream is the answer for a report-style command: stdout whenever it has
/// content — even on a non-zero exit, which is how `pdf --doctor` says "not
/// ready" — otherwise stderr, as a real error. Split out so the rule is tested
/// without spawning a process.
fn output_or_error(stdout: String, stderr: String) -> Result<String, String> {
    if stdout.trim().is_empty() {
        return Err(stderr);
    }
    Ok(stdout)
}

/// Readiness of the PDF pipeline for a theme — pandoc/typst plus the theme's
/// declared fonts — as the binary's JSON report. The GUI renders it as a setup
/// checklist so a missing tool or font produces install steps instead of a bare
/// "not found on PATH" (or, for fonts, a silently wrong-looking PDF).
#[tauri::command]
async fn pdf_doctor(theme: String) -> Result<String, String> {
    let mut args = vec!["pdf".into(), "--doctor".into(), "--json".into()];
    if !theme.is_empty() {
        args.push("--theme".into());
        args.push(theme);
    }
    tauri::async_runtime::spawn_blocking(move || run_csb_output(&args))
        .await
        .map_err(|e| format!("pdf-doctor task failed: {e}"))?
}

/// Open a tool or font download page from the PDF setup report in the user's real
/// browser. Restricted to http(s) so this can never be used to launch an
/// arbitrary local program.
#[tauri::command]
fn open_external(url: String) -> Result<(), String> {
    if !url.starts_with("https://") && !url.starts_with("http://") {
        return Err("Only http(s) links can be opened.".into());
    }
    os_open(&url)
}

/// PDF-readiness of an item: "none" | "incomplete" | "complete" (backlog #5), so
/// the GUI can warn before generating without reimplementing completeness.
#[tauri::command]
async fn pdf_status(portal: String, kind: String, id: String) -> Result<String, String> {
    let args = vec![
        "pdf-status".into(),
        portal_flag(&portal).into(),
        kind_flag(&kind, false).into(),
        id,
    ];
    let out = tauri::async_runtime::spawn_blocking(move || run_csb(&args))
        .await
        .map_err(|e| format!("pdf-status task failed: {e}"))??;
    Ok(out.trim().to_string())
}

/// Generate a styled PDF for an item (backlog #5). A path cascades to its
/// courses + labs. --force silences the binary's incompleteness warning because
/// the GUI already warns the user up front (via pdf_status).
#[tauri::command]
async fn generate_pdf(
    portal: String,
    kind: String,
    id: String,
    theme: String,
) -> Result<(), String> {
    let mut args = vec![
        "pdf".into(),
        portal_flag(&portal).into(),
        kind_flag(&kind, false).into(),
        id,
        "--force".into(),
    ];
    if !theme.is_empty() {
        args.push("--theme".into());
        args.push(theme);
    }
    tauri::async_runtime::spawn_blocking(move || run_csb(&args))
        .await
        .map_err(|e| format!("generate-pdf task failed: {e}"))??;
    Ok(())
}

/// Open a stored item's generated PDF in the OS default app (backlog #5).
/// Resolves the .pdf sibling of the vault .md via `mdpath`, so the GUI never
/// reimplements the vault layout or filename sanitization.
#[tauri::command]
async fn open_pdf(portal: String, kind: String, id: String) -> Result<(), String> {
    let args = vec![
        "mdpath".into(),
        portal_flag(&portal).into(),
        kind_flag(&kind, false).into(),
        id,
    ];
    let md = tauri::async_runtime::spawn_blocking(move || run_csb(&args))
        .await
        .map_err(|e| format!("mdpath task failed: {e}"))??
        .trim()
        .to_string();
    if md.is_empty() {
        return Err("PDF path not found.".into());
    }
    let pdf = match md.strip_suffix(".md") {
        Some(stripped) => format!("{stripped}.pdf"),
        None => format!("{md}.pdf"),
    };
    os_open(&pdf)
}

/// Delete a stored item — ledger row + per-item JSON + vault .md/.pdf (backlog
/// #17). --yes skips the binary's prompt; the GUI shows its own confirm modal.
#[tauri::command]
async fn delete_item(portal: String, kind: String, id: String) -> Result<(), String> {
    let args = vec![
        "db".into(),
        "rm".into(),
        portal_flag(&portal).into(),
        kind_flag(&kind, false).into(),
        id,
        "--yes".into(),
    ];
    tauri::async_runtime::spawn_blocking(move || run_csb(&args))
        .await
        .map_err(|e| format!("delete task failed: {e}"))??;
    Ok(())
}

/// Rename a stored item — updates the ledger row and per-item JSON title, and
/// drops the stale vault .md/.pdf (backlog #17).
#[tauri::command]
async fn rename_item(
    portal: String,
    kind: String,
    id: String,
    name: String,
) -> Result<(), String> {
    let args = vec![
        "db".into(),
        "set".into(),
        portal_flag(&portal).into(),
        kind_flag(&kind, false).into(),
        id,
        "--name".into(),
        name,
    ];
    tauri::async_runtime::spawn_blocking(move || run_csb(&args))
        .await
        .map_err(|e| format!("rename task failed: {e}"))??;
    Ok(())
}

/// Path to the persistent fetching-list file, in the app data dir. The frontend
/// owns the JSON schema; these commands only do file I/O so the list survives
/// restarts and is a real, inspectable file on disk.
fn queue_file(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("could not resolve app data dir: {e}"))?;
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir.join("fetch-queue.json"))
}

/// Load the persisted fetching list (raw JSON). Returns "{}" when no file exists.
#[tauri::command]
fn queue_load(app: AppHandle) -> Result<String, String> {
    let path = queue_file(&app)?;
    match std::fs::read_to_string(&path) {
        Ok(s) => Ok(s),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok("{}".into()),
        Err(e) => Err(e.to_string()),
    }
}

/// Persist the fetching list — the frontend passes the serialized JSON verbatim.
#[tauri::command]
fn queue_save(app: AppHandle, data: String) -> Result<(), String> {
    let path = queue_file(&app)?;
    std::fs::write(&path, data).map_err(|e| e.to_string())
}

/// Path to the persistent session file, in the app data dir. Holds the GUI's
/// stateful session (portal, active tab, in-progress fetch descriptor, and the
/// started/ended/clean-exit lifecycle markers) so a relaunch can restore an
/// in-progress session and tell a graceful stop from a sudden interruption. The
/// frontend owns the schema; these commands only do file I/O.
fn session_file(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("could not resolve app data dir: {e}"))?;
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir.join("session.json"))
}

/// Read the session JSON at path, returning "{}" when the file doesn't exist
/// (a first run). Path-based so it can be exercised against a real temp file.
fn read_session(path: &Path) -> Result<String, String> {
    match std::fs::read_to_string(path) {
        Ok(s) => Ok(s),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok("{}".into()),
        Err(e) => Err(e.to_string()),
    }
}

/// Write the session JSON verbatim to path.
fn write_session(path: &Path, data: &str) -> Result<(), String> {
    std::fs::write(path, data).map_err(|e| e.to_string())
}

/// Load the persisted session (raw JSON). Returns "{}" when no file exists.
#[tauri::command]
fn session_load(app: AppHandle) -> Result<String, String> {
    read_session(&session_file(&app)?)
}

/// Persist the session — the frontend passes the serialized JSON verbatim.
#[tauri::command]
fn session_save(app: AppHandle, data: String) -> Result<(), String> {
    write_session(&session_file(&app)?, &data)
}

/// Current wall-clock time in milliseconds since the Unix epoch (matches the
/// frontend's Date.now(), so session timestamps are consistent across both).
fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

/// Return the session JSON stamped as gracefully stopped: endedAt=now,
/// cleanExit=true, fetchActive=false. This is the authoritative "clean close"
/// marker — a crash or force-kill never runs it, so the next launch sees
/// cleanExit still false and knows the previous session was interrupted. Pure and
/// tolerant of an empty/invalid file (starts from an empty object), so the
/// close-handler can call it best-effort.
fn stopped_session_json(existing: &str, now: u64) -> String {
    let mut v = serde_json::from_str::<serde_json::Value>(existing).unwrap_or_else(|_| serde_json::json!({}));
    if !v.is_object() {
        v = serde_json::json!({});
    }
    let obj = v.as_object_mut().expect("value is an object");
    obj.insert("endedAt".into(), serde_json::json!(now));
    obj.insert("cleanExit".into(), serde_json::json!(true));
    obj.insert("fetchActive".into(), serde_json::json!(false));
    v.to_string()
}

/// Stamp the session file at path as gracefully stopped. Best-effort and
/// path-based so the close path is testable against a real temp file.
fn mark_stopped_at(path: &Path) {
    let existing = std::fs::read_to_string(path).unwrap_or_default();
    let _ = std::fs::write(path, stopped_session_json(&existing, now_ms()));
}

/// On a clean window close, stamp the session file as gracefully stopped.
/// Best-effort: any I/O error is ignored (a missing marker just makes the next
/// launch treat this session as interrupted, which is the safe default).
fn mark_session_stopped(app: &AppHandle) {
    let Ok(path) = session_file(app) else { return };
    mark_stopped_at(&path);
}

// ---------------------------------------------------------------------------
// Settings: the GUI Settings dialog persists the user's chosen folders (data,
// vault, logs, Chrome profile, PDF theme dir) and default portal. These map onto
// the SAME env keys the Go core (and the Python app) already honor with
// precedence env > config.yaml > default, so the GUI steers where files go by
// injecting CSB_* env vars on every spawn — no core change required.
// ---------------------------------------------------------------------------

/// Live CSB_* env overrides applied to every skills-scraper spawn. Seeded at
/// startup from settings.json and refreshed by settings_save. Empty in a dev
/// checkout with no configured settings, so today's repo-relative behavior is
/// unchanged; a bundle fills in writable defaults (see refresh_settings_env).
static SETTINGS_ENV: OnceLock<Mutex<Vec<(String, String)>>> = OnceLock::new();

fn settings_env() -> &'static Mutex<Vec<(String, String)>> {
    SETTINGS_ENV.get_or_init(|| Mutex::new(Vec::new()))
}

/// The env pairs to apply to a spawned skills-scraper command.
fn csb_env() -> Vec<(String, String)> {
    settings_env().lock().unwrap().clone()
}

fn set_csb_env(pairs: Vec<(String, String)>) {
    *settings_env().lock().unwrap() = pairs;
}

/// True when running from a real repo checkout (dev) rather than a packaged
/// bundle. In dev we leave the path env vars UNSET for any key the user hasn't
/// configured, so the Go core keeps its repo-relative defaults; a bundle has no
/// checkout, so it must supply writable absolute defaults instead.
fn is_dev_checkout() -> bool {
    candidate_roots()
        .iter()
        .any(|r| r.join(".git").exists() && r.join("go").exists())
}

/// Read a nested string from a settings/defaults JSON value (`section.key`),
/// trimmed. Returns "" when missing. A section of "" reads a top-level key.
fn json_path_str(root: &serde_json::Value, section: &str, key: &str) -> String {
    let node = if section.is_empty() {
        root.get(key)
    } else {
        root.get(section).and_then(|s| s.get(key))
    };
    node.and_then(|x| x.as_str()).unwrap_or("").trim().to_string()
}

/// True when a path points inside a macOS .app bundle (e.g. a themes folder under
/// Contents/Resources). Such a path is never a durable user setting — it breaks
/// the moment the app is renamed, moved, or updated — so a persisted value like
/// this is ignored and the live default (the current bundle) is used instead.
fn is_bundle_internal(path: &str) -> bool {
    path.contains("/Contents/Resources/") || path.contains(".app/")
}

/// Build the CSB_* env overrides from the settings JSON. A configured (non-empty)
/// value maps to its env var; a blank/absent key falls back to `defaults` only
/// when `use_defaults` is true (a bundle). A persisted value that points inside an
/// app bundle is treated as unset (see is_bundle_internal), so the live default
/// wins — this self-heals a stale themes path baked in by an older build. Pure and
/// tolerant of invalid JSON, so it is unit-tested and safe to call best-effort.
fn env_overrides_from(
    settings_json: &str,
    defaults: &serde_json::Value,
    use_defaults: bool,
) -> Vec<(String, String)> {
    let v = serde_json::from_str::<serde_json::Value>(settings_json)
        .unwrap_or_else(|_| serde_json::json!({}));
    // (env var, section, key) — portal is a top-level key (section "").
    let mapping = [
        ("CSB_DATA", "paths", "data"),
        ("CSB_VAULT", "paths", "vault"),
        ("CSB_LOG_DIR", "paths", "logs"),
        ("CSB_PROFILE_DIR", "paths", "profile"),
        ("CSB_THEME_DIR", "paths", "themes"),
        ("CSB_PORTAL", "", "portal"),
    ];
    let mut out = Vec::new();
    for (env, section, key) in mapping {
        let mut val = json_path_str(&v, section, key);
        if is_bundle_internal(&val) {
            val = String::new();
        }
        if val.is_empty() && use_defaults {
            val = json_path_str(defaults, section, key);
        }
        if !val.is_empty() {
            out.push((env.to_string(), val));
        }
    }
    out
}

/// The folder name a bundled app uses for its user data under ~/Documents and
/// ~/Downloads. Matches the app's display name (no space), which is a little
/// awkward but keeps the on-disk folder recognizable as this app's.
const APP_DIR_NAME: &str = "SkillsScraper";

/// Assemble a bundle's default-paths JSON from the resolved base dirs. Pure, so
/// the Documents/Downloads split — data/vault/logs under Documents, the large
/// Chrome profile under Downloads (away from iCloud sync) — is unit-tested.
fn bundle_default_paths(
    docs: &Path,
    downloads: &Path,
    theme: &Path,
) -> serde_json::Value {
    serde_json::json!({
        "paths": {
            "data": docs.join("data").display().to_string(),
            "vault": docs.join("vault").display().to_string(),
            "logs": docs.join("logs").display().to_string(),
            "profile": downloads.join("profile").display().to_string(),
            "themes": theme.display().to_string(),
        },
        "portal": "public"
    })
}

/// The effective default directory for each configurable path — what a blank
/// field resolves to. Used as the live env fallback and as the placeholder values
/// shown in the dialog (recomputed each time, so the themes path always tracks the
/// current app bundle). In dev the defaults mirror the Go core's repo-relative
/// names exactly; in a bundle data/vault/logs live under ~/Documents/SkillsScraper
/// and the (large) Chrome profile under ~/Downloads/SkillsScraper; theme comes
/// from the bundled resources.
fn default_paths(app: &AppHandle) -> serde_json::Value {
    if is_dev_checkout() {
        let root = repo_root();
        return serde_json::json!({
            "paths": {
                "data": root.join("data").display().to_string(),
                "vault": root.join("csbmdvault").display().to_string(),
                "logs": root.join("logs").display().to_string(),
                "profile": root.join(".webdriver_profiles").display().to_string(),
                "themes": root.join("theme").display().to_string(),
            },
            "portal": "public"
        });
    }
    // A packaged app defaults its user data to a visible folder named after the
    // app: ~/Documents/SkillsScraper/{data,vault,logs}. The Chrome profile is
    // large and Documents is often synced to iCloud, so the profile lives under
    // ~/Downloads/SkillsScraper/profile instead. Themes stay in the read-only app
    // bundle (see below).
    let app_dir = |base: Result<PathBuf, tauri::Error>| {
        base.or_else(|_| app.path().app_data_dir())
            .unwrap_or_else(|_| PathBuf::from("."))
            .join(APP_DIR_NAME)
    };
    let docs = app_dir(app.path().document_dir());
    let downloads = app_dir(app.path().download_dir());
    let theme = app
        .path()
        .resource_dir()
        .map(|r| r.join("theme"))
        .unwrap_or_else(|_| docs.join("theme"));
    bundle_default_paths(&docs, &downloads, &theme)
}

/// Recompute and store the live CSB_* env overrides from the given settings JSON.
fn refresh_settings_env(app: &AppHandle, settings_json: &str) {
    let defaults = default_paths(app);
    let use_defaults = !is_dev_checkout();
    set_csb_env(env_overrides_from(settings_json, &defaults, use_defaults));
}

/// On startup: load whatever settings are on disk (empty when none) into the live
/// env overrides applied to every spawn. Deliberately does NOT seed a file — a
/// bundle's writable defaults are resolved live by env_overrides_from, so nothing
/// absolute is baked in (which is what let an old themes path go stale). The file
/// is written only when the user actually saves a choice.
fn init_settings_env(app: &AppHandle) {
    let json = match settings_file(app) {
        Ok(path) => std::fs::read_to_string(&path).unwrap_or_else(|_| "{}".to_string()),
        Err(_) => "{}".to_string(),
    };
    refresh_settings_env(app, &json);
}

/// Path to the persistent settings file, in the app data dir (next to
/// session.json / fetch-queue.json). The frontend owns the schema; these commands
/// only do file I/O plus applying the resulting env overrides.
fn settings_file(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("could not resolve app data dir: {e}"))?;
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir.join("settings.json"))
}

/// Load the persisted settings (raw JSON). Returns "{}" when no file exists.
#[tauri::command]
fn settings_load(app: AppHandle) -> Result<String, String> {
    let path = settings_file(&app)?;
    match std::fs::read_to_string(&path) {
        Ok(s) => Ok(s),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok("{}".into()),
        Err(e) => Err(e.to_string()),
    }
}

/// Persist the settings — the frontend passes the serialized JSON verbatim — then
/// apply the new paths immediately so the very next spawn uses them.
#[tauri::command]
fn settings_save(app: AppHandle, data: String) -> Result<(), String> {
    let path = settings_file(&app)?;
    std::fs::write(&path, &data).map_err(|e| e.to_string())?;
    refresh_settings_env(&app, &data);
    Ok(())
}

/// The effective default for each path/portal (what a blank field resolves to),
/// as JSON, so the dialog can show them as placeholders.
#[tauri::command]
fn settings_defaults(app: AppHandle) -> Result<String, String> {
    Ok(default_paths(&app).to_string())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(BrowserSession(Mutex::new(None)))
        .manage(BrowserGuard(Arc::new(AtomicBool::new(false))))
        .manage(FetchState(Arc::new(Mutex::new(None))))
        .manage(FetchStdin(Arc::new(Mutex::new(None))))
        // Seed the live CSB_* env overrides from settings.json (and, in a bundle,
        // write writable first-run defaults) before any command can spawn the Go
        // binary, so the user's chosen folders take effect from the first fetch.
        .setup(|app| {
            init_settings_env(&app.handle().clone());
            Ok(())
        })
        // Closing the window must not orphan a browser. SIGTERM any running
        // fetch and any open login subprocess so the Go binary shuts Chrome down
        // cleanly and releases the profile lock (otherwise the next run launches
        // on a locked profile and loads without the signed-in session).
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                if let Some(pid) = *window.state::<FetchState>().0.lock().unwrap() {
                    sigterm(pid);
                }
                if let Some(child) = window.state::<BrowserSession>().0.lock().unwrap().as_ref() {
                    sigterm(child.id());
                }
                // Record a graceful stop so the next launch can tell this clean
                // close from a crash (which never reaches here).
                mark_session_stopped(window.app_handle());
            }
        })
        .invoke_handler(tauri::generate_handler![
            list_items,
            sync_items,
            search_items,
            fetch,
            stop_fetch,
            continue_fetch,
            open_browser,
            close_browser,
            browser_status,
            open_vault,
            open_md,
            list_themes,
            pdf_status,
            pdf_doctor,
            open_external,
            generate_pdf,
            open_pdf,
            delete_item,
            rename_item,
            queue_load,
            queue_save,
            session_load,
            session_save,
            settings_load,
            settings_save,
            settings_defaults
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn browser_guard_is_single_flight() {
        let g = BrowserGuard(Arc::new(AtomicBool::new(false)));
        assert!(g.try_acquire(), "first acquire should succeed");
        assert!(!g.try_acquire(), "second acquire must fail while held");
        g.release();
        assert!(g.try_acquire(), "acquire should succeed again after release");
        // A clone shares the same flag, so it also sees "held".
        assert!(!g.clone().try_acquire(), "clone must observe the held flag");
        g.release();
    }

    // Multiple ids must reach the binary as ONE comma-joined value (the -p/-c/-l
    // flag takes a single token). Both "1, 2, 3" and "1 2 3" arrive here already
    // split by the frontend, so we just verify the join.
    #[test]
    fn fetch_args_joins_multiple_ids() {
        let ids = vec!["1".to_string(), "2".to_string(), "3".to_string()];
        let a = fetch_args("public", "path", &ids, false, false, false, false, false);
        assert_eq!(a, vec!["fetch", "-A", "-p", "1,2,3", "--emit-progress"]);
    }

    // A single id still works and empties are dropped.
    #[test]
    fn fetch_args_single_id() {
        let ids = vec!["16".to_string(), "".to_string()];
        let a = fetch_args("partner", "course", &ids, false, false, false, false, false);
        assert_eq!(a, vec!["fetch", "-B", "-c", "16", "--emit-progress"]);
    }

    // "all" (any case) switches to bulk mode for the selected type.
    #[test]
    fn fetch_args_all_is_bulk_mode() {
        let a = fetch_args(
            "partner",
            "lab",
            &["ALL".to_string()],
            false,
            false,
            false,
            false,
            false,
        );
        assert_eq!(a, vec!["fetch", "-B", "--all", "labs", "--emit-progress"]);
    }

    // A clean close stamps the lifecycle markers while preserving the frontend's
    // other session fields (portal, tab, …) untouched.
    #[test]
    fn stopped_session_preserves_fields_and_marks_clean() {
        let existing = r#"{"startedAt":1000,"portal":"partner","tab":"browse","fetchActive":true}"#;
        let out = stopped_session_json(existing, 2000);
        let v: serde_json::Value = serde_json::from_str(&out).unwrap();
        assert_eq!(v["startedAt"], 1000);
        assert_eq!(v["portal"], "partner");
        assert_eq!(v["tab"], "browse");
        assert_eq!(v["endedAt"], 2000);
        assert_eq!(v["cleanExit"], true);
        assert_eq!(v["fetchActive"], false); // a closed window has nothing running
    }

    // End-to-end against a REAL file on disk: first-run default, save/load
    // round-trip, crash leaves cleanExit=false, and a clean close stamps the file
    // gracefully stopped while preserving the frontend's other fields.
    #[test]
    fn session_file_roundtrip_and_markers() {
        let dir = std::env::temp_dir().join(format!(
            "csbgui-sess-test-{}-{}",
            std::process::id(),
            now_ms()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("session.json");

        // A missing file reads back as "{}" (first run).
        assert_eq!(read_session(&path).unwrap(), "{}");

        // Save a running session (cleanExit=false) and read it back verbatim.
        let running = r#"{"startedAt":1000,"cleanExit":false,"portal":"partner","tab":"browse","fetchActive":true}"#;
        write_session(&path, running).unwrap();
        let loaded: serde_json::Value =
            serde_json::from_str(&read_session(&path).unwrap()).unwrap();
        // A session never marked clean reads back as interrupted — the crash case.
        assert_eq!(loaded["cleanExit"], false);
        assert_eq!(loaded["fetchActive"], true);
        assert_eq!(loaded["portal"], "partner");

        // A clean close stamps the real file and preserves the other fields.
        mark_stopped_at(&path);
        let after: serde_json::Value =
            serde_json::from_str(&read_session(&path).unwrap()).unwrap();
        assert_eq!(after["cleanExit"], true);
        assert_eq!(after["fetchActive"], false);
        assert!(after["endedAt"].as_u64().unwrap() > 0); // a real timestamp was written
        assert_eq!(after["startedAt"], 1000); // untouched
        assert_eq!(after["tab"], "browse"); // untouched

        std::fs::remove_dir_all(&dir).ok();
    }

    // An empty or corrupt session file still yields a valid clean-close marker.
    #[test]
    fn stopped_session_tolerates_empty_or_invalid() {
        for input in ["", "{}", "not json", "[1,2,3]"] {
            let v: serde_json::Value =
                serde_json::from_str(&stopped_session_json(input, 5)).unwrap();
            assert_eq!(v["cleanExit"], true);
            assert_eq!(v["endedAt"], 5);
            assert_eq!(v["fetchActive"], false);
        }
    }

    // Flags are appended after the ids.
    #[test]
    fn fetch_args_forwards_flags() {
        let ids = vec!["5".to_string()];
        let a = fetch_args("public", "path", &ids, true, true, false, false, true);
        assert_eq!(
            a,
            vec![
                "fetch",
                "-A",
                "-p",
                "5",
                "--force",
                "--signin",
                "--headless",
                "--emit-progress"
            ]
        );
    }

    // A configured (non-empty) path wins over the default; other keys fall back
    // to the default (bundle mode); portal is a top-level key.
    #[test]
    fn env_overrides_configured_value_wins() {
        let defaults = serde_json::json!({
            "paths": {"data": "/def/data", "vault": "/def/vault", "themes": "/def/theme"},
            "portal": "public"
        });
        let settings = r#"{"paths":{"data":"/my/data","vault":"  "},"portal":"partner"}"#;
        let env = env_overrides_from(settings, &defaults, true);
        assert!(env.contains(&("CSB_DATA".into(), "/my/data".into())));
        // blank (whitespace-only) vault falls back to the default in bundle mode
        assert!(env.contains(&("CSB_VAULT".into(), "/def/vault".into())));
        assert!(env.contains(&("CSB_THEME_DIR".into(), "/def/theme".into())));
        assert!(env.contains(&("CSB_PORTAL".into(), "partner".into())));
    }

    // In dev (use_defaults=false) an unset key injects NOTHING, so the Go core
    // keeps its repo-relative default; in a bundle the default is injected.
    #[test]
    fn env_overrides_blank_uses_default_only_in_bundle() {
        let defaults = serde_json::json!({"paths": {"data": "/def/data"}, "portal": "public"});
        let dev = env_overrides_from("{}", &defaults, false);
        assert!(dev.is_empty(), "dev must inject nothing for unset keys: {dev:?}");
        let bundle = env_overrides_from("{}", &defaults, true);
        assert!(bundle.contains(&("CSB_DATA".into(), "/def/data".into())));
        assert!(bundle.contains(&("CSB_PORTAL".into(), "public".into())));
    }

    // Invalid JSON is tolerated: it resolves as if no keys were configured (so a
    // bundle still gets its defaults; a default-less key stays unset).
    #[test]
    fn env_overrides_tolerates_invalid_json() {
        let defaults = serde_json::json!({"paths": {"data": "/def/data"}});
        let env = env_overrides_from("not json", &defaults, true);
        assert!(env.contains(&("CSB_DATA".into(), "/def/data".into())));
        assert!(!env.iter().any(|(k, _)| k == "CSB_PORTAL"));
    }

    // A bundle's default paths split by kind: data/vault/logs under Documents,
    // but the large Chrome profile under Downloads (Documents is iCloud-synced).
    #[test]
    fn bundle_defaults_put_profile_in_downloads() {
        let docs = PathBuf::from("/Users/me/Documents/SkillsScraper");
        let downloads = PathBuf::from("/Users/me/Downloads/SkillsScraper");
        let theme = PathBuf::from("/Applications/SkillsScraper.app/Contents/Resources/theme");
        let v = bundle_default_paths(&docs, &downloads, &theme);
        assert_eq!(v["paths"]["data"], "/Users/me/Documents/SkillsScraper/data");
        assert_eq!(v["paths"]["vault"], "/Users/me/Documents/SkillsScraper/vault");
        assert_eq!(v["paths"]["logs"], "/Users/me/Documents/SkillsScraper/logs");
        assert_eq!(v["paths"]["profile"], "/Users/me/Downloads/SkillsScraper/profile");
        assert_eq!(
            v["paths"]["themes"],
            "/Applications/SkillsScraper.app/Contents/Resources/theme"
        );
    }

    // A persisted path baked inside an app bundle (a stale themes seed from an
    // older build) is ignored, so the live default — the current bundle — wins.
    #[test]
    fn env_overrides_ignores_stale_bundle_internal_path() {
        assert!(is_bundle_internal(
            "/Applications/Google Skills Scraper.app/Contents/Resources/theme"
        ));
        assert!(!is_bundle_internal("/Users/me/Documents/SkillsScraper/themes"));

        let defaults = serde_json::json!({
            "paths": {"themes": "/Applications/SkillsScraper.app/Contents/Resources/theme"}
        });
        let settings =
            r#"{"paths":{"themes":"/Applications/Google Skills Scraper.app/Contents/Resources/theme"}}"#;
        let env = env_overrides_from(settings, &defaults, true);
        // The stale saved value is dropped; the live (current-bundle) default wins.
        assert!(env.contains(&(
            "CSB_THEME_DIR".into(),
            "/Applications/SkillsScraper.app/Contents/Resources/theme".into()
        )));
    }

    // `pdf --doctor --json` prints its report AND exits non-zero when the
    // toolchain is incomplete — which is precisely the report the setup dialog
    // exists to show. Treating that exit code as a failure would swallow it.
    #[test]
    fn report_output_survives_a_nonzero_exit() {
        let json = "{\"ok\":false}".to_string();
        assert_eq!(
            output_or_error(json.clone(), "ignored warning".into()),
            Ok(json)
        );
    }

    #[test]
    fn report_with_no_output_is_an_error() {
        assert_eq!(
            output_or_error("   \n".into(), "binary not found".into()),
            Err("binary not found".into())
        );
    }
}

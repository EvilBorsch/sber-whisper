use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, ChildStderr, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

use arboard::Clipboard;
use chrono::Local;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Emitter, Manager, Runtime, WebviewWindow};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt as _};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};

const SETTINGS_FILE_NAME: &str = "app_settings.json";
const APP_LOG_NAME: &str = "app.log";
const LOG_ROTATE_SIZE_BYTES: u64 = 2 * 1024 * 1024;
const TRAY_ICON: tauri::image::Image<'_> = tauri::include_image!("./icons/32x32.png");

#[derive(Debug, Clone, Serialize, Deserialize)]
struct AppSettings {
    hotkey: String,
    popup_timeout_sec: u64,
    auto_launch: bool,
    language_mode: String,
    theme: String,
}

impl Default for AppSettings {
    fn default() -> Self {
        #[cfg(target_os = "macos")]
        let default_hotkey = "Cmd+G".to_string();
        #[cfg(not(target_os = "macos"))]
        let default_hotkey = "Ctrl+G".to_string();

        Self {
            hotkey: default_hotkey,
            popup_timeout_sec: 10,
            auto_launch: false,
            language_mode: "ru".to_string(),
            theme: "siri_aurora".to_string(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
struct LegacySettings {
    hotkey: Option<String>,
    hotkey_windows: Option<String>,
    hotkey_macos: Option<String>,
    popup_timeout_sec: Option<u64>,
    auto_launch: Option<bool>,
    language_mode: Option<String>,
    theme: Option<String>,
}

struct SidecarProcess {
    child: Child,
    stdin: ChildStdin,
}

struct SharedState {
    settings: Mutex<AppSettings>,
    sidecar: Mutex<Option<SidecarProcess>>,
    recording_started: AtomicBool,
    shutdown: AtomicBool,
}

impl SharedState {
    fn new(settings: AppSettings) -> Self {
        Self {
            settings: Mutex::new(settings),
            sidecar: Mutex::new(None),
            recording_started: AtomicBool::new(false),
            shutdown: AtomicBool::new(false),
        }
    }
}

fn ensure_log_file(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = logs_dir(app)?;
    fs::create_dir_all(&dir).map_err(|e| format!("failed to create log dir: {e}"))?;

    let path = dir.join(APP_LOG_NAME);
    if let Ok(metadata) = fs::metadata(&path) {
        if metadata.len() > LOG_ROTATE_SIZE_BYTES {
            let rotated = dir.join("app.log.1");
            let _ = fs::remove_file(&rotated);
            fs::rename(&path, rotated).map_err(|e| format!("failed to rotate app log: {e}"))?;
        }
    }

    Ok(path)
}

fn log_line(app: &AppHandle, line: &str) {
    if let Ok(path) = ensure_log_file(app) {
        if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(path) {
            let ts = Local::now().format("%Y-%m-%d %H:%M:%S");
            let _ = writeln!(f, "[{ts}] {line}");
        }
    }
}

fn app_config_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_config_dir()
        .map_err(|e| format!("failed to resolve app config dir: {e}"))?;
    fs::create_dir_all(&dir).map_err(|e| format!("failed to create app config dir: {e}"))?;
    Ok(dir)
}

fn logs_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app_config_dir(app)?.join("logs");
    fs::create_dir_all(&dir).map_err(|e| format!("failed to create logs dir: {e}"))?;
    Ok(dir)
}

fn settings_path(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(app_config_dir(app)?.join(SETTINGS_FILE_NAME))
}

fn load_settings_from_disk(app: &AppHandle) -> AppSettings {
    let path = match settings_path(app) {
        Ok(p) => p,
        Err(_) => return AppSettings::default(),
    };

    let raw = match fs::read_to_string(path) {
        Ok(v) => v,
        Err(_) => return AppSettings::default(),
    };

    if let Ok(settings) = serde_json::from_str::<AppSettings>(&raw) {
        return settings;
    }

    if let Ok(legacy) = serde_json::from_str::<LegacySettings>(&raw) {
        let mut settings = AppSettings::default();
        settings.hotkey = legacy
            .hotkey
            .or(legacy.hotkey_windows)
            .or(legacy.hotkey_macos)
            .unwrap_or(settings.hotkey);

        if let Some(timeout) = legacy.popup_timeout_sec {
            settings.popup_timeout_sec = timeout;
        }
        if let Some(auto_launch) = legacy.auto_launch {
            settings.auto_launch = auto_launch;
        }
        if let Some(language_mode) = legacy.language_mode {
            settings.language_mode = language_mode;
        }
        if let Some(theme) = legacy.theme {
            settings.theme = theme;
        }
        return settings;
    }

    AppSettings::default()
}

fn save_settings_to_disk(app: &AppHandle, settings: &AppSettings) -> Result<(), String> {
    let path = settings_path(app)?;
    let file = File::create(path).map_err(|e| format!("failed to create settings file: {e}"))?;
    serde_json::to_writer_pretty(file, settings)
        .map_err(|e| format!("failed to write settings file: {e}"))?;
    Ok(())
}

fn apply_autostart(app: &AppHandle, enabled: bool) -> Result<(), String> {
    if enabled {
        app.autolaunch()
            .enable()
            .map_err(|e| format!("failed to enable auto-launch: {e}"))?;
    } else {
        if let Err(e) = app.autolaunch().disable() {
            // Some platforms/plugins return "not found" when auto-launch is already absent.
            let msg = e.to_string();
            if msg.contains("os error 2") {
                log_line(app, &format!("auto-launch entry already absent, continuing: {msg}"));
            } else {
                return Err(format!("failed to disable auto-launch: {e}"));
            }
        }
    }
    Ok(())
}

fn parse_shortcut(hotkey: &str) -> Result<Shortcut, String> {
    hotkey
        .parse::<Shortcut>()
        .map_err(|e| format!("invalid hotkey '{hotkey}': {e}"))
}

fn register_shortcut(app: &AppHandle, hotkey: &str) -> Result<(), String> {
    let shortcut = parse_shortcut(hotkey)?;
    let manager = app.global_shortcut();
    manager
        .unregister_all()
        .map_err(|e| format!("failed to unregister shortcuts: {e}"))?;
    manager
        .register(shortcut)
        .map_err(|e| format!("failed to register shortcut: {e}"))?;
    Ok(())
}

fn emit_asr_event(app: &AppHandle, payload: &Value) {
    let _ = app.emit("asr_event", payload.clone());
}

fn copy_text_to_clipboard(app: &AppHandle, text: &str) {
    match Clipboard::new().and_then(|mut cb| cb.set_text(text.to_string())) {
        Ok(_) => log_line(app, "copied transcript to clipboard"),
        Err(e) => {
            log_line(app, &format!("clipboard copy failed: {e}"));
            emit_asr_event(
                app,
                &json!({
                    "event": "error",
                    "message": format!("Clipboard copy failed: {e}")
                }),
            );
        }
    }
}

fn find_python_script(app: &AppHandle) -> Result<PathBuf, String> {
    let mut checked: Vec<PathBuf> = Vec::new();
    let mut candidates: Vec<PathBuf> = vec![
        PathBuf::from("python").join("asr_service.py"),
        PathBuf::from("_up_").join("python").join("asr_service.py"),
        PathBuf::from("..").join("python").join("asr_service.py"),
        PathBuf::from("..").join("_up_").join("python").join("asr_service.py"),
        PathBuf::from("..").join("..").join("python").join("asr_service.py"),
    ];

    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd.join("python").join("asr_service.py"));
        candidates.push(cwd.join("_up_").join("python").join("asr_service.py"));
        candidates.push(cwd.join("..").join("python").join("asr_service.py"));
        candidates.push(cwd.join("..").join("_up_").join("python").join("asr_service.py"));
    }

    if let Ok(exe_path) = std::env::current_exe() {
        for base in exe_path.ancestors().take(7) {
            candidates.push(base.join("python").join("asr_service.py"));
            candidates.push(base.join("_up_").join("python").join("asr_service.py"));
            candidates.push(base.join("..").join("python").join("asr_service.py"));
            candidates.push(base.join("..").join("_up_").join("python").join("asr_service.py"));
        }
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        candidates.push(resource_dir.join("python").join("asr_service.py"));
        candidates.push(resource_dir.join("_up_").join("python").join("asr_service.py"));
        candidates.push(resource_dir.join("asr_service.py"));
    }

    for path in candidates {
        checked.push(path.clone());
        if path.exists() {
            return Ok(path);
        }
    }

    Err(format!(
        "python/asr_service.py not found (checked {} paths)",
        checked.len()
    ))
}

fn sidecar_binary_name() -> &'static str {
    #[cfg(target_os = "windows")]
    {
        "sber-whisper-sidecar.exe"
    }
    #[cfg(target_os = "macos")]
    {
        "sber-whisper-sidecar"
    }
    #[cfg(all(not(target_os = "windows"), not(target_os = "macos")))]
    {
        "sber-whisper-sidecar"
    }
}

fn find_sidecar_binary(app: &AppHandle) -> Result<PathBuf, String> {
    let binary = sidecar_binary_name();
    let mut checked: Vec<PathBuf> = Vec::new();
    let mut candidates: Vec<PathBuf> = vec![
        PathBuf::from("python")
            .join("dist")
            .join("sber-whisper-sidecar")
            .join(binary),
        PathBuf::from("_up_")
            .join("python")
            .join("dist")
            .join("sber-whisper-sidecar")
            .join(binary),
        PathBuf::from("..")
            .join("python")
            .join("dist")
            .join("sber-whisper-sidecar")
            .join(binary),
        PathBuf::from("..")
            .join("_up_")
            .join("python")
            .join("dist")
            .join("sber-whisper-sidecar")
            .join(binary),
        PathBuf::from("..")
            .join("..")
            .join("python")
            .join("dist")
            .join("sber-whisper-sidecar")
            .join(binary),
    ];

    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(
            cwd.join("python")
                .join("dist")
                .join("sber-whisper-sidecar")
                .join(binary),
        );
        candidates.push(
            cwd.join("_up_")
                .join("python")
                .join("dist")
                .join("sber-whisper-sidecar")
                .join(binary),
        );
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        candidates.push(
            resource_dir
                .join("python")
                .join("dist")
                .join("sber-whisper-sidecar")
                .join(binary),
        );
        candidates.push(
            resource_dir
                .join("_up_")
                .join("python")
                .join("dist")
                .join("sber-whisper-sidecar")
                .join(binary),
        );
        candidates.push(resource_dir.join("sber-whisper-sidecar").join(binary));
    }

    if let Ok(exe_path) = std::env::current_exe() {
        for base in exe_path.ancestors().take(7) {
            candidates.push(
                base.join("python")
                    .join("dist")
                    .join("sber-whisper-sidecar")
                    .join(binary),
            );
            candidates.push(
                base.join("_up_")
                    .join("python")
                    .join("dist")
                    .join("sber-whisper-sidecar")
                    .join(binary),
            );
            candidates.push(base.join("sber-whisper-sidecar").join(binary));
        }
    }

    for path in candidates {
        checked.push(path.clone());
        if path.exists() {
            return Ok(path);
        }
    }

    Err(format!(
        "bundled sidecar binary '{}' not found (checked {} paths)",
        binary,
        checked.len()
    ))
}

fn allow_script_fallback() -> bool {
    if cfg!(debug_assertions) {
        return true;
    }

    match std::env::var("SBER_WHISPER_ALLOW_SCRIPT_FALLBACK") {
        Ok(raw) => {
            let value = raw.trim();
            value == "1" || value.eq_ignore_ascii_case("true")
        }
        Err(_) => false,
    }
}

fn spawn_sidecar_command(
    app: &AppHandle,
    mut cmd: Command,
    label: &str,
) -> Result<SidecarProcess, String> {
    #[cfg(target_os = "windows")]
    {
        // Sidecar is a console executable; prevent terminal window from flashing/opening.
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    cmd.stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("failed to spawn sidecar '{label}': {e}"))?;

    let stdin = child
        .stdin
        .take()
        .ok_or_else(|| "failed to capture sidecar stdin".to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "failed to capture sidecar stdout".to_string())?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| "failed to capture sidecar stderr".to_string())?;

    spawn_stdout_reader(app.clone(), stdout);
    spawn_stderr_reader(app.clone(), stderr);

    log_line(app, &format!("started sidecar with '{label}'"));
    Ok(SidecarProcess { child, stdin })
}

fn hide_settings_window_inner(app: &AppHandle) -> Result<(), String> {
    let settings = settings_window(app)?;
    settings
        .hide()
        .map_err(|e| format!("failed to hide settings: {e}"))?;
    Ok(())
}

fn current_hotkey(settings: &AppSettings) -> &str {
    settings.hotkey.trim()
}

fn validate_hotkey(settings: &AppSettings) -> Result<(), String> {
    let hotkey = current_hotkey(settings);
    if hotkey.is_empty() {
        return Err("hotkey cannot be empty".to_string());
    }
    parse_shortcut(hotkey)?;
    Ok(())
}

fn start_sidecar_process(app: &AppHandle) -> Result<SidecarProcess, String> {
    let logs = logs_dir(app)?;
    let mut errors: Vec<String> = Vec::new();

    match find_sidecar_binary(app) {
        Ok(sidecar_bin) => {
            let mut cmd = Command::new(&sidecar_bin);
            cmd.env("SBER_WHISPER_LOG_DIR", logs.to_string_lossy().to_string())
                .env("PYTHONUNBUFFERED", "1")
                .env("PYTHONIOENCODING", "utf-8")
                .env("PYTHONUTF8", "1");

            match spawn_sidecar_command(app, cmd, &sidecar_bin.to_string_lossy()) {
                Ok(proc) => return Ok(proc),
                Err(e) => errors.push(e),
            }
        }
        Err(e) => {
            log_line(app, &e);
            errors.push(e);
        }
    }

    if !allow_script_fallback() {
        return Err(format!(
            "failed to start bundled ASR sidecar; reinstall app. details: {}",
            errors.join(" | ")
        ));
    }

    log_line(
        app,
        "sidecar script fallback enabled; attempting to run python/asr_service.py",
    );
    let script = find_python_script(app)?;

    let mut attempts: Vec<(String, Vec<String>)> = vec![
        (
            "python".to_string(),
            vec![script.to_string_lossy().to_string()],
        ),
        (
            "python3".to_string(),
            vec![script.to_string_lossy().to_string()],
        ),
    ];

    #[cfg(target_os = "windows")]
    {
        attempts.push((
            "py".to_string(),
            vec!["-3".to_string(), script.to_string_lossy().to_string()],
        ));
    }

    let mut last_err = String::new();

    for (bin, args) in attempts {
        let mut cmd = Command::new(&bin);
        cmd.args(args)
            .env("SBER_WHISPER_LOG_DIR", logs.to_string_lossy().to_string())
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1");

        match spawn_sidecar_command(app, cmd, &bin) {
            Ok(proc) => return Ok(proc),
            Err(e) => {
                last_err = e;
                errors.push(last_err.clone());
            }
        }
    }

    Err(format!(
        "failed to start sidecar process ({last_err}); details: {}",
        errors.join(" | ")
    ))
}

fn spawn_stdout_reader(app: AppHandle, stdout: ChildStdout) {
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        let mut reader = reader;
        let mut buffer: Vec<u8> = Vec::new();

        loop {
            buffer.clear();
            match reader.read_until(b'\n', &mut buffer) {
                Ok(0) => break,
                Ok(_) => {
                    while let Some(last) = buffer.last() {
                        if *last == b'\n' || *last == b'\r' {
                            buffer.pop();
                        } else {
                            break;
                        }
                    }
                    if buffer.is_empty() {
                        continue;
                    }

                    let raw = match String::from_utf8(buffer.clone()) {
                        Ok(text) => text,
                        Err(_) => {
                            log_line(&app, "sidecar stdout contained non-UTF8 bytes; decoding lossy");
                            String::from_utf8_lossy(&buffer).into_owned()
                        }
                    };

                    match serde_json::from_str::<Value>(&raw) {
                        Ok(payload) => {
                            if payload.get("event") == Some(&Value::String("final_transcript".to_string())) {
                                if let Some(text) = payload.get("text").and_then(Value::as_str) {
                                    copy_text_to_clipboard(&app, text);
                                }
                            }

                            if payload.get("event") == Some(&Value::String("ready".to_string())) {
                                log_line(&app, "sidecar ready event received");
                            }

                            emit_asr_event(&app, &payload);
                        }
                        Err(e) => {
                            log_line(&app, &format!("invalid sidecar JSON '{raw}': {e}"));
                        }
                    }
                }
                Err(e) => {
                    log_line(&app, &format!("sidecar stdout read error: {e}"));
                    break;
                }
            }
        }

        let shared = app.state::<SharedState>();
        shared.recording_started.store(false, Ordering::SeqCst);

        emit_asr_event(
            &app,
            &json!({
                "event": "error",
                "message": "ASR sidecar disconnected. It will restart on next action."
            }),
        );
    });
}

fn spawn_stderr_reader(app: AppHandle, stderr: ChildStderr) {
    std::thread::spawn(move || {
        let reader = BufReader::new(stderr);
        for line in reader.lines() {
            if let Ok(raw) = line {
                if !raw.trim().is_empty() {
                    log_line(&app, &format!("sidecar stderr: {raw}"));
                }
            }
        }
    });
}

fn ensure_sidecar_running(app: &AppHandle, shared: &SharedState) -> Result<(), String> {
    let mut guard = shared
        .sidecar
        .lock()
        .map_err(|_| "failed to lock sidecar mutex".to_string())?;

    let needs_restart = if let Some(proc) = guard.as_mut() {
        match proc.child.try_wait() {
            Ok(Some(status)) => {
                log_line(app, &format!("sidecar exited with status {status}"));
                true
            }
            Ok(None) => false,
            Err(e) => {
                log_line(app, &format!("sidecar try_wait failed: {e}"));
                true
            }
        }
    } else {
        true
    };

    if needs_restart {
        *guard = Some(start_sidecar_process(app)?);
    }

    Ok(())
}

fn send_sidecar_command(app: &AppHandle, command: Value) -> Result<(), String> {
    let shared = app.state::<SharedState>();
    ensure_sidecar_running(app, &shared)?;

    let mut guard = shared
        .sidecar
        .lock()
        .map_err(|_| "failed to lock sidecar mutex".to_string())?;

    let proc = guard
        .as_mut()
        .ok_or_else(|| "sidecar is not available".to_string())?;

    let line = format!("{}\n", command);
    proc.stdin
        .write_all(line.as_bytes())
        .map_err(|e| format!("failed to write sidecar command: {e}"))?;
    proc.stdin
        .flush()
        .map_err(|e| format!("failed to flush sidecar command: {e}"))?;

    Ok(())
}

fn popup_window<R: Runtime>(app: &AppHandle<R>) -> Result<WebviewWindow<R>, String> {
    app.get_webview_window("popup")
        .ok_or_else(|| "popup window not found".to_string())
}

fn settings_window<R: Runtime>(app: &AppHandle<R>) -> Result<WebviewWindow<R>, String> {
    app.get_webview_window("settings")
        .ok_or_else(|| "settings window not found".to_string())
}

fn position_popup<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let popup = popup_window(app)?;
    let monitor = popup
        .current_monitor()
        .map_err(|e| format!("failed to read monitor: {e}"))?
        .ok_or_else(|| "no monitor found".to_string())?;

    let monitor_size = monitor.size();
    let scale = monitor.scale_factor();
    let popup_size = popup
        .outer_size()
        .map_err(|e| format!("failed to read popup size: {e}"))?;

    let x = monitor_size.width as f64 - popup_size.width as f64 - 20.0;
    let y = 20.0;

    popup
        .set_position(tauri::Position::Logical(tauri::LogicalPosition::new(
            x / scale,
            y / scale,
        )))
        .map_err(|e| format!("failed to set popup position: {e}"))?;

    Ok(())
}

fn show_popup(app: &AppHandle) {
    if let Ok(popup) = popup_window(app) {
        if let Err(e) = position_popup(app) {
            log_line(app, &format!("popup positioning error: {e}"));
        }

        let _ = popup.show();
        let _ = popup.set_focus();
    }
}

fn hide_popup_inner(app: &AppHandle) -> Result<(), String> {
    let popup = popup_window(app)?;
    popup.hide().map_err(|e| format!("failed to hide popup: {e}"))?;
    Ok(())
}

fn send_command_or_emit_error(app: &AppHandle, payload: Value) {
    if let Err(err) = send_sidecar_command(app, payload) {
        log_line(app, &format!("sidecar command failed: {err}"));
        emit_asr_event(app, &json!({ "event": "error", "message": err }));
    }
}

fn handle_hotkey_press(app: &AppHandle) {
    let shared = app.state::<SharedState>();

    if shared
        .recording_started
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_ok()
    {
        show_popup(app);
        send_command_or_emit_error(app, json!({ "command": "start_recording" }));
    }
}

fn handle_hotkey_release(app: &AppHandle) {
    let shared = app.state::<SharedState>();

    if shared
        .recording_started
        .compare_exchange(true, false, Ordering::SeqCst, Ordering::SeqCst)
        .is_ok()
    {
        show_popup(app);
        send_command_or_emit_error(app, json!({ "command": "stop_and_transcribe" }));
    }
}

#[tauri::command]
fn get_settings(app: AppHandle) -> Result<AppSettings, String> {
    let shared = app.state::<SharedState>();
    let settings = shared
        .settings
        .lock()
        .map_err(|_| "failed to lock settings mutex".to_string())?;
    Ok(settings.clone())
}

#[tauri::command]
fn save_settings(app: AppHandle, settings: AppSettings) -> Result<AppSettings, String> {
    if settings.popup_timeout_sec == 0 || settings.popup_timeout_sec > 120 {
        return Err("popup timeout must be between 1 and 120 seconds".to_string());
    }

    validate_hotkey(&settings)?;

    save_settings_to_disk(&app, &settings)?;
    register_shortcut(&app, current_hotkey(&settings))?;
    apply_autostart(&app, settings.auto_launch)?;

    let shared = app.state::<SharedState>();
    {
        let mut guard = shared
            .settings
            .lock()
            .map_err(|_| "failed to lock settings mutex".to_string())?;
        *guard = settings.clone();
    }

    send_command_or_emit_error(
        &app,
        json!({
            "command": "set_config",
            "config": {
                "language_mode": settings.language_mode.clone(),
                "popup_timeout_sec": settings.popup_timeout_sec
            }
        }),
    );

    log_line(&app, "settings updated");
    Ok(settings)
}

#[tauri::command]
fn hide_popup(app: AppHandle) -> Result<(), String> {
    hide_popup_inner(&app)
}

#[tauri::command]
fn open_settings_window(app: AppHandle) -> Result<(), String> {
    let settings = settings_window(&app)?;
    settings
        .show()
        .map_err(|e| format!("failed to show settings: {e}"))?;
    settings
        .set_focus()
        .map_err(|e| format!("failed to focus settings: {e}"))?;
    Ok(())
}

#[tauri::command]
fn hide_settings_window(app: AppHandle) -> Result<(), String> {
    hide_settings_window_inner(&app)
}

#[tauri::command]
fn start_recording(app: AppHandle) {
    let shared = app.state::<SharedState>();
    shared.recording_started.store(true, Ordering::SeqCst);
    show_popup(&app);
    send_command_or_emit_error(&app, json!({ "command": "start_recording" }));
}

#[tauri::command]
fn stop_and_transcribe(app: AppHandle) {
    let shared = app.state::<SharedState>();
    shared.recording_started.store(false, Ordering::SeqCst);
    show_popup(&app);
    send_command_or_emit_error(&app, json!({ "command": "stop_and_transcribe" }));
}

#[tauri::command]
fn cancel_current(app: AppHandle) {
    let shared = app.state::<SharedState>();
    shared.recording_started.store(false, Ordering::SeqCst);
    send_command_or_emit_error(&app, json!({ "command": "cancel_current" }));
}

#[tauri::command]
fn healthcheck(app: AppHandle) {
    send_command_or_emit_error(&app, json!({ "command": "healthcheck" }));
}

fn init_sidecar(app: &AppHandle) {
    let shared = app.state::<SharedState>();

    if let Err(e) = ensure_sidecar_running(app, &shared) {
        log_line(app, &format!("failed to start sidecar at setup: {e}"));
        emit_asr_event(app, &json!({ "event": "error", "message": e }));
        return;
    }

    send_command_or_emit_error(app, json!({ "command": "init" }));
}

fn build_tray(app: &AppHandle) -> Result<(), String> {
    let settings_item = MenuItem::with_id(app, "settings", "Settings", true, None::<&str>)
        .map_err(|e| format!("failed to create settings menu item: {e}"))?;
    let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)
        .map_err(|e| format!("failed to create quit menu item: {e}"))?;

    let menu = Menu::with_items(app, &[&settings_item, &quit_item])
        .map_err(|e| format!("failed to create tray menu: {e}"))?;

    let tray = TrayIconBuilder::new()
        .icon(TRAY_ICON.clone())
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "settings" => {
                let _ = open_settings_window(app.clone());
            }
            "quit" => {
                app.exit(0);
            }
            _ => {}
        })
        .build(app)
        .map_err(|e| format!("failed to create tray icon: {e}"))?;

    // Tauri requires keeping TrayIcon handle alive; dropping it removes tray icon and may exit app.
    std::mem::forget(tray);

    Ok(())
}

fn setup_windows(app: &AppHandle) {
    if let Ok(popup) = popup_window(app) {
        let _ = popup.hide();
        let _ = popup.set_always_on_top(true);
    }

    if let Ok(settings) = settings_window(app) {
        let _ = settings.hide();
    }
}

fn setup_app(app: &AppHandle) -> Result<(), String> {
    let settings = load_settings_from_disk(app);
    save_settings_to_disk(app, &settings)?;

    let shared = app.state::<SharedState>();
    {
        let mut guard = shared
            .settings
            .lock()
            .map_err(|_| "failed to lock settings mutex".to_string())?;
        *guard = settings.clone();
    }
    shared.recording_started.store(false, Ordering::SeqCst);
    shared.shutdown.store(false, Ordering::SeqCst);

    setup_windows(app);
    build_tray(app)?;
    validate_hotkey(&settings)?;
    register_shortcut(app, current_hotkey(&settings))?;
    apply_autostart(app, settings.auto_launch)?;

    init_sidecar(app);
    log_line(app, "application setup complete");

    Ok(())
}

fn cleanup_sidecar(app: &AppHandle) {
    let proc_to_stop: Option<SidecarProcess> = {
        let shared = app.state::<SharedState>();
        shared.shutdown.store(true, Ordering::SeqCst);
        let taken = match shared.sidecar.lock() {
            Ok(mut guard) => guard.take(),
            Err(_) => None,
        };
        taken
    };

    if let Some(mut proc) = proc_to_stop {
        let _ = proc
            .stdin
            .write_all(format!("{}\n", json!({ "command": "shutdown" })).as_bytes());
        let _ = proc.stdin.flush();
        let _ = proc.child.kill();
        let _ = proc.child.wait();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(SharedState::new(AppSettings::default()))
        .plugin(tauri_plugin_store::Builder::default().build())
        .plugin(tauri_plugin_global_shortcut::Builder::new().with_handler(
            |app, _shortcut, event| match event.state {
                ShortcutState::Pressed => handle_hotkey_press(app),
                ShortcutState::Released => handle_hotkey_release(app),
            },
        ).build())
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec!["--silent"]),
        ))
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            setup_app(&app.handle()).map_err(|e| -> Box<dyn std::error::Error> {
                Box::new(std::io::Error::new(std::io::ErrorKind::Other, e))
            })?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_settings,
            save_settings,
            hide_popup,
            open_settings_window,
            hide_settings_window,
            start_recording,
            stop_and_transcribe,
            cancel_current,
            healthcheck,
        ])
        .on_window_event(|window, event| {
            if window.label() == "popup" {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }

            if window.label() == "settings" {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to build tauri app")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                cleanup_sidecar(app);
            }
        });
}

#[cfg(test)]
mod tests {
    use super::{parse_shortcut, AppSettings};

    #[test]
    fn settings_default_timeout_is_ten() {
        let settings = AppSettings::default();
        assert_eq!(settings.popup_timeout_sec, 10);
    }

    #[test]
    fn parses_valid_hotkey() {
        let parsed = parse_shortcut("Ctrl+G");
        assert!(parsed.is_ok());
    }

    #[test]
    fn rejects_invalid_hotkey() {
        let parsed = parse_shortcut("not-a-hotkey");
        assert!(parsed.is_err());
    }
}

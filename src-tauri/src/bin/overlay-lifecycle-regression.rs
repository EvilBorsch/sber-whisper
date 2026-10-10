// Test-only Windows harness: production popup visibility + real bundled frontend.
#[cfg(target_os = "windows")]
mod windows {
    use serde_json::{json, Value};
    use std::io::{self, BufRead};
    use tauri::{AppHandle, Emitter, Manager, WebviewUrl, WebviewWindowBuilder};

    #[tauri::command]
    fn get_settings() -> Value {
        json!({"hotkey":"Ctrl+G","popup_timeout_sec":10,"model_keepalive_min":5,
            "auto_launch":false,"language_mode":"ru","theme":"siri_aurora"})
    }

    #[tauri::command]
    fn hide_popup(app: AppHandle) -> Result<(), String> {
        sber_whisper_lib::hide_popup_inner(&app)
    }

    #[tauri::command]
    fn cancel_current() {}

    #[tauri::command]
    fn open_settings_window() {}

    pub fn run() {
        let mut context = tauri::generate_context!();
        context.config_mut().app.windows.clear();
        context.config_mut().identifier = "com.pingv.sberwhisper.lifecycle-test".into();
        tauri::Builder::default()
            .invoke_handler(tauri::generate_handler![
                get_settings,
                hide_popup,
                cancel_current,
                open_settings_window
            ])
            .setup(|app| {
                WebviewWindowBuilder::new(app, "popup", WebviewUrl::App("index.html".into()))
                    .title("Sber Whisper Lifecycle Regression")
                    .data_directory(
                        std::env::temp_dir()
                            .join(format!("sber-overlay-lifecycle-{}", std::process::id())),
                    )
                    .additional_browser_args("--remote-debugging-port=9227")
                    .visible(false)
                    .focused(false)
                    .focusable(false)
                    .decorations(false)
                    .resizable(false)
                    .shadow(false)
                    .transparent(true)
                    .always_on_top(true)
                    .skip_taskbar(true)
                    .inner_size(400.0, 84.0)
                    .build()?;
                sber_whisper_lib::hide_popup_inner(app.handle())?;
                let app = app.handle().clone();
                std::thread::spawn(move || {
                    for line in io::stdin().lock().lines() {
                        let Ok(line) = line else { break };
                        let Ok(payload) = serde_json::from_str::<Value>(&line) else {
                            continue;
                        };
                        match payload["command"].as_str().unwrap_or("") {
                            "show" => {
                                sber_whisper_lib::show_popup(&app);
                                assert!(!app
                                    .get_webview_window("popup")
                                    .unwrap()
                                    .is_focused()
                                    .unwrap());
                            }
                            "event" => {
                                app.emit("asr_event", payload["payload"].clone()).unwrap();
                            }
                            "quit" => {
                                app.exit(0);
                                break;
                            }
                            _ => {}
                        }
                    }
                    app.exit(0);
                });
                Ok(())
            })
            .run(context)
            .expect("run lifecycle regression");
    }
}

#[cfg(target_os = "windows")]
fn main() {
    windows::run();
}

#[cfg(not(target_os = "windows"))]
fn main() {}

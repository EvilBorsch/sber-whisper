// Windows integration regression: revealing the popup must also reveal its WebView.
#[cfg(target_os = "windows")]
fn main() {
    use tauri::{Manager, Webview, WebviewUrl, WebviewWindowBuilder};
    let mut context = tauri::generate_context!();
    context.config_mut().app.windows.clear();
    tauri::Builder::default()
        .setup(|app| {
            WebviewWindowBuilder::new(app, "popup", WebviewUrl::App("index.html".into()))
                .data_directory(
                    std::env::temp_dir()
                        .join(format!("sber-overlay-regression-{}", std::process::id())),
                )
                .visible(false)
                .focused(false)
                .focusable(false)
                .decorations(false)
                .skip_taskbar(true)
                .inner_size(400.0, 84.0)
                .build()?;
            let app = app.handle().clone();
            std::thread::spawn(move || {
                std::thread::sleep(std::time::Duration::from_millis(500));
                println!("Checking actual native WebView visibility");
                let popup = app.get_webview_window("popup").unwrap();
                let webview: &Webview = popup.as_ref();
                webview.hide().unwrap();
                sber_whisper_lib::show_popup(&app);
                popup
                    .with_webview(|platform| unsafe {
                        let mut visible = Default::default();
                        platform.controller().IsVisible(&mut visible).unwrap();
                        if visible.as_bool() {
                            println!("PASS: popup WebView is visible");
                            std::process::exit(0);
                        }
                        eprintln!("FAIL: native popup shown but WebView is hidden");
                        std::process::exit(1);
                    })
                    .unwrap();
            });
            Ok(())
        })
        .run(context)
        .expect("run regression app");
}

#[cfg(not(target_os = "windows"))]
fn main() {}

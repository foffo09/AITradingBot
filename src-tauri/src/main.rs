#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod service;
use service::Service;
use std::sync::Mutex;
use tauri::Manager;

fn main() {
    let app = tauri::Builder::default()
        .on_window_event(|window, event| {
            if window.label() == "main" && matches!(event, tauri::WindowEvent::Destroyed) {
                window.app_handle().exit(0);
            }
        })
        .setup(|app| {
            let resources = app.path().resource_dir()?;
            let binary_name = if cfg!(windows) {
                "aitradingbot-service.exe"
            } else {
                "aitradingbot-service"
            };
            let installed = std::env::current_exe()?
                .parent()
                .ok_or("Directory eseguibile mancante")?
                .join(binary_name);
            let binary = if cfg!(debug_assertions) && !installed.is_file() {
                let suffix = if cfg!(windows) { ".exe" } else { "" };
                std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                    .join("binaries")
                    .join(format!(
                        "aitradingbot-service-{}{}",
                        env!("SIDECAR_TARGET"),
                        suffix
                    ))
            } else {
                installed
            };
            let ui = if cfg!(debug_assertions) {
                std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../frontend/dist")
            } else {
                resources.join("ui")
            };
            let service = Service::start(
                &binary,
                &ui,
                &app.path().app_data_dir()?.join("local-service"),
            )
            .map_err(std::io::Error::other)?;
            let origin = service.url.clone();
            let url = origin.parse()?;
            app.manage(Mutex::new(Some(service)));
            tauri::WebviewWindowBuilder::new(app, "main", tauri::WebviewUrl::External(url))
                .title("AITradingBot · Terminale analitico")
                .inner_size(1440.0, 960.0)
                .min_inner_size(760.0, 600.0)
                .on_navigation(move |url| url.origin().ascii_serialization() == origin)
                .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Impossibile avviare AITradingBot. Verificare asset e backend confezionato.");
    app.run(|app, event| {
        if let tauri::RunEvent::Exit = event {
            if let Some(state) = app.try_state::<Mutex<Option<Service>>>() {
                if let Ok(mut service) = state.lock() {
                    service.take();
                }
            }
        }
    });
}

fn main() {
    println!(
        "cargo:rustc-env=SIDECAR_TARGET={}",
        std::env::var("TARGET").unwrap()
    );
    tauri_build::build()
}

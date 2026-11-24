// 桌面入口：所有逻辑在 lib.rs，便于单测复用。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    yoai_desktop_tauri_lib::run()
}

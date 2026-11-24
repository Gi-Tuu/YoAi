//! YoAi Desktop Tauri 桥：管理 Python runtime 子进程，转发命令与事件。
//! 不碰 Agent Core 语义——只是 JSONL 管道 + 生命周期管理。

use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;

use tauri::{Emitter, Manager, State};

pub struct RuntimeState {
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<ChildStdin>>,
}

impl RuntimeState {
    fn new() -> Self {
        Self { child: Mutex::new(None), stdin: Mutex::new(None) }
    }
}

/// 定位 Python runtime 脚本与解释器。
/// 开发模式：用配置/环境变量指定的 Python；打包模式：随包附带的嵌入式 Python。
fn runtime_paths(app: &tauri::AppHandle) -> (PathBuf, PathBuf) {
    let resource = app.path().resource_dir().ok();
    let script = if let Some(dir) = &resource {
        let bundled = dir.join("runtime").join("yoai_runtime.py");
        if bundled.exists() { bundled } else { dev_root().join("runtime").join("yoai_runtime.py") }
    } else {
        dev_root().join("runtime").join("yoai_runtime.py")
    };
    let python = if let Some(dir) = &resource {
        let embedded = dir.join("python").join("python.exe");
        if embedded.exists() { embedded } else { std::env::var("YOAI_PYTHON").map(PathBuf::from).unwrap_or_else(|_| PathBuf::from("python")) }
    } else {
        std::env::var("YOAI_PYTHON").map(PathBuf::from).unwrap_or_else(|_| PathBuf::from("python"))
    };
    (python, script)
}

/// 开发模式：src-tauri/target/... → 工程根
fn dev_root() -> PathBuf {
    let here = std::env::current_dir().unwrap_or_default();
    for ancestor in here.ancestors() {
        if ancestor.join("runtime").join("yoai_runtime.py").exists() {
            return ancestor.to_path_buf();
        }
    }
    here
}

fn spawn_runtime(app: &tauri::AppHandle, state: &RuntimeState) -> Result<(), String> {
    let (python, script) = runtime_paths(app);
    let data_dir = app.path().app_data_dir().map_err(|e| e.to_string())?;
    std::fs::create_dir_all(&data_dir).map_err(|e| e.to_string())?;

    let mut child = Command::new(&python)
        .arg(&script)
        .current_dir(script.parent().unwrap_or(std::path::Path::new(".")))
        .env("YOAI_DATA_DIR", &data_dir)
        .env("PYTHONUNBUFFERED", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("启动 Python runtime 失败（{}）：{}", python.display(), e))?;

    let stdin = child.stdin.take().ok_or("无法取得 runtime stdin")?;
    let stdout = child.stdout.take().ok_or("无法取得 runtime stdout")?;

    *state.stdin.lock().unwrap() = Some(stdin);
    *state.child.lock().unwrap() = Some(child);

    // stdout 读线程：每行 JSON → emit 到前端（后台接收与前台渲染分离）
    let emitter = app.clone();
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            match line {
                Ok(line) if line.trim().is_empty() => continue,
                Ok(line) => {
                    if let Ok(value) = serde_json::from_str::<serde_json::Value>(&line) {
                        let _ = emitter.emit("runtime://message", value);
                    } else {
                        let _ = emitter.emit("runtime://message", serde_json::json!({
                            "v": 1, "type": "error", "stage": "protocol",
                            "message": "runtime 输出非法 JSON（stdout 被污染？）"
                        }));
                    }
                }
                Err(e) => {
                    let _ = emitter.emit("runtime://message", serde_json::json!({
                        "v": 1, "type": "error", "stage": "runtime", "message": e.to_string()
                    }));
                    break;
                }
            }
        }
    });

    // stderr 读线程：只 logging，不进协议
    // （此处不 emit 到前端，避免污染事件流；打包版可写日志文件）
    Ok(())
}

#[tauri::command]
fn ipc_send(json: String, state: State<'_, RuntimeState>) -> Result<(), String> {
    let mut guard = state.stdin.lock().map_err(|e| e.to_string())?;
    let stdin = guard.as_mut().ok_or("Python runtime 未启动")?;
    writeln!(stdin, "{}", json).map_err(|e| format!("写入 runtime 失败：{}", e))?;
    stdin.flush().map_err(|e| e.to_string())
}

#[tauri::command]
fn runtime_status(state: State<'_, RuntimeState>) -> bool {
    state.child.lock().map(|g| g.as_ref().is_some_and(|c| c.id() > 0)).unwrap_or(false)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(RuntimeState::new())
        .setup(|app| {
            let state = app.state::<RuntimeState>();
            if let Err(e) = spawn_runtime(app.handle(), &state) {
                let _ = app.handle().emit("runtime://message", serde_json::json!({
                    "v": 1, "type": "error", "stage": "startup", "message": e
                }));
            }
            // 托盘图标（阶段 D）：点击显示主窗，退出走 shutdown
            use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder};
            use tauri::menu::{Menu, MenuItem};
            if let Ok(quit) = MenuItem::with_id(app, "quit", "退出 YoAi", true, None::<&str>) {
                if let Ok(show) = MenuItem::with_id(app, "show", "显示主窗口", true, None::<&str>) {
                    if let Ok(menu) = Menu::with_items(app, &[&show, &quit]) {
                        let _ = TrayIconBuilder::new()
                            .menu(&menu)
                            .on_menu_event(|app, event| match event.id().as_ref() {
                                "quit" => app.exit(0),
                                "show" => { if let Some(w) = app.get_webview_window("main") { let _ = w.show(); let _ = w.set_focus(); } }
                                _ => {}
                            })
                            .on_tray_icon_event(|tray, event| {
                                if let tauri::tray::TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                                    if let Some(w) = tray.app_handle().get_webview_window("main") { let _ = w.show(); let _ = w.set_focus(); }
                                }
                            })
                            .build(app);
                    }
                }
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(state) = window.try_state::<RuntimeState>() {
                    // 优雅退出：shutdown 后等待子进程，避免残留
                    if let Some(mut stdin) = state.stdin.lock().unwrap().take() {
                        let _ = writeln!(stdin, "{}", r#"{"v":1,"type":"shutdown"}"#);
                        let _ = stdin.flush();
                    }
                    if let Some(mut child) = state.child.lock().unwrap().take() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
            }
        })
        .invoke_handler(tauri::generate_handler![ipc_send, runtime_status])
        .run(tauri::generate_context!())
        .expect("YoAi Tauri 启动失败");
}

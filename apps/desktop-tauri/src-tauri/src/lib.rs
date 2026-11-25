//! YoAi Desktop Tauri 桥：管理 Python runtime 子进程，转发命令与事件。
//! 不碰 Agent Core 语义——只是 JSONL 管道 + 生命周期管理。

use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

/// Windows：隐藏 Python 子进程的控制台窗口（CREATE_NO_WINDOW = 0x08000000）。
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

use tauri::{Emitter, Manager, State, WebviewUrl, WebviewWindowBuilder};

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
    // Windows 隐藏 Python 子进程控制台；非 Windows 用空函数 no-op。
    #[cfg(windows)]
    fn hide_console(cmd: &mut Command) { cmd.creation_flags(CREATE_NO_WINDOW); }
    #[cfg(not(windows))]
    fn hide_console(_cmd: &mut Command) {}

    let mut cmd = Command::new(&python);
    cmd.arg(&script)
        .current_dir(script.parent().unwrap_or(std::path::Path::new(".")))
        // 数据目录由 runtime 自举（dist/runtime → dist/output，保留旧端会话数据）；
        // 不再注入 Tauri AppData，否则新旧端数据分家。
        .env("PYTHONUNBUFFERED", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    hide_console(&mut cmd);
    let mut child = cmd
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

/// 打开/聚焦一个信息浮窗（钉住能力）。无边框、置顶、可拖动、可缩放，能浮到桌面任意位置。
/// 浮窗加载同一前端，带 ?float=<kind> 查询参数；数据由主窗口 emit 过来，浮窗不连 runtime。
#[tauri::command]
fn open_float_panel(app: tauri::AppHandle, kind: String, title: String) -> Result<(), String> {
    let label = format!("float-{}", kind);
    if let Some(w) = app.get_webview_window(&label) {
        let _ = w.show();
        return Ok(());   // 已存在则只显示，不重复建窗
    }
    // WebviewUrl::App 只接受路径（不接受查询串），否则会找名为 "index.html?float=x" 的文件→白屏。
    // 用初始化脚本注入浮窗标识，main.tsx 读 window.__FLOAT_KIND__ 分流。
    let init = format!("window.__FLOAT_KIND__ = {:?};", kind);
    WebviewWindowBuilder::new(&app, &label, WebviewUrl::App("index.html".into()))
        .title(&title)
        .initialization_script(&init)
        .inner_size(320.0, 260.0)
        .min_inner_size(220.0, 160.0)
        .decorations(false)      // 自绘标题栏（纸墨风格）
        .transparent(true)
        .always_on_top(true)
        .skip_taskbar(true)
        .resizable(true)
        .build()
        .map_err(|e| format!("创建浮窗失败：{}", e))?;
    Ok(())
}

/// 悬停即出窗：创建/显示浮窗并按锚点的屏幕坐标定位（贴近方块，避开对话区方向由前端算好传入）。
/// 浮窗不抢焦点（set_focus 不调用），避免打断主窗口输入。
#[tauri::command]
fn hover_float_panel(
    app: tauri::AppHandle, kind: String, title: String,
    x: f64, y: f64, _width: f64, height: f64,
) -> Result<(), String> {
    let label = format!("float-{}", kind);
    let win = if let Some(w) = app.get_webview_window(&label) {
        w
    } else {
        let init = format!("window.__FLOAT_KIND__ = {:?};", kind);
        WebviewWindowBuilder::new(&app, &label, WebviewUrl::App("index.html".into()))
            .title(&title)
            .initialization_script(&init)
            .inner_size(320.0, 260.0)
            .min_inner_size(220.0, 160.0)
            .decorations(false)
            .transparent(true)
            .always_on_top(true)
            .skip_taskbar(true)
            .resizable(true)
            .focused(false)          // 悬停浮窗不抢主窗口焦点
            .build()
            .map_err(|e| format!("创建浮窗失败：{}", e))?
    };
    // 定位：默认放在锚点左侧（右侧锚点），钳制到主屏可见区
    let px = x - 320.0 - 8.0;
    let py = y + height / 2.0 - 130.0;
    let _ = win.set_position(tauri::LogicalPosition::new(px.max(4.0), py.max(4.0)));
    let _ = win.show();
    Ok(())
}

/// 浮窗鼠标进入/离开由前端 emit 通知主窗口协调延迟关闭；这里转发事件给主窗。
#[tauri::command]
fn float_hover_signal(app: tauri::AppHandle, kind: String, entering: bool) -> Result<(), String> {
    let _ = app.emit("float://hover-signal", serde_json::json!({
        "kind": kind, "entering": entering,
    }));
    Ok(())
}

#[tauri::command]
fn close_float_panel(app: tauri::AppHandle, label: String) -> Result<(), String> {
    if let Some(w) = app.get_webview_window(&label) {
        let _ = w.close();
    }
    Ok(())
}

/// 主窗口把最新 snapshot 推送给已存在的浮窗；浮窗不存在时静默跳过（没钉住）。
#[tauri::command]
fn push_float_data(app: tauri::AppHandle, payload: String) -> Result<(), String> {
    for kind in ["facts", "goals", "memory"] {
        let label = format!("float-{}", kind);
        if app.get_webview_window(&label).is_some() {
            let _ = app.emit_to(&label, "float://data", &payload);
        }
    }
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        // 单实例守卫（对齐旧端 QLocalSocket 语义）：第二实例把已运行的窗口唤到前台
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
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
            // 关键：只有主窗口关闭才 shutdown runtime。浮窗关闭不能杀掉 Python 子进程。
            if window.label() != "main" { return; }
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
        .invoke_handler(tauri::generate_handler![
            ipc_send, runtime_status, open_float_panel, close_float_panel, push_float_data,
            hover_float_panel, float_hover_signal
        ])
        .run(tauri::generate_context!())
        .expect("YoAi Tauri 启动失败");
}

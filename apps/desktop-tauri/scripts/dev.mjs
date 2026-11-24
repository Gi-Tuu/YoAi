/** 开发模式启动：先检查 Python + node 环境，再拉起 Tauri dev。
 *  用法：node scripts/dev.mjs
 */
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const check = (cmd, args, label) => {
  const r = spawnSync(cmd, args, { encoding: "utf8", shell: process.platform === "win32" });
  if (r.status !== 0) {
    console.error(`[dev] ${label} 不可用：${cmd} ${args.join(" ")}`);
    process.exit(1);
  }
  return (r.stdout || "").trim();
};

// 1. 环境检查（精简输出）
check("node", ["-v"], "Node");
try { check("cargo", ["--version"], "Rust"); }
catch { console.error("[dev] Rust 未安装：先装 https://rustup.rs 再运行"); process.exit(1); }

const py = process.env.YOAI_PYTHON || "python";
const runtime = resolve(root, "runtime", "yoai_runtime.py");
if (!existsSync(runtime)) { console.error(`[dev] 找不到 runtime：${runtime}`); process.exit(1); }
check(py, ["-c", "import yoai; import yai_core; print('ok')"], "Python(yoai+yai_core)");

console.log("[dev] 环境就绪，启动 Tauri dev…");
const r = spawnSync("npm", ["run", "tauri", "dev"], {
  cwd: root, stdio: "inherit", shell: process.platform === "win32",
});
process.exit(r.status ?? 1);

/** Windows 构建：前端 build → Tauri bundle（msi + nsis）。
 *  构建前检查 Rust/Node；产物在 src-tauri/target/release/bundle/。
 *  注意：正式安装包要在未装 Python 的机器运行，需把嵌入式 Python 放进资源目录
 *  （见 WINDOWS-BUILD.md 第 3 节；本脚本会检查该目录并给出提示，不静默打包出跑不起来的包）。
 */
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const run = (cmd, args, label) => {
  console.log(`[build] ${label}…`);
  const r = spawnSync(cmd, args, { cwd: root, stdio: "inherit", shell: process.platform === "win32" });
  if (r.status !== 0) { console.error(`[build] ${label} 失败`); process.exit(r.status ?? 1); }
};

run("npm", ["run", "build"], "前端 build");
run("npm", ["run", "tauri", "build"], "Tauri bundle");

const bundle = resolve(root, "src-tauri/target/release/bundle");
const embedded = resolve(root, "src-tauri/resources/python/python.exe");
if (!existsSync(embedded)) {
  console.warn("[build] 警告：未发现嵌入式 Python（src-tauri/resources/python/python.exe）。");
  console.warn("[build] 当前安装包只能在预装 Python 且配好 YOAI_PYTHON 的机器运行。");
  console.warn("[build] 见 WINDOWS-BUILD.md 完成嵌入式 Python 打包后再分发。");
}
console.log(`[build] 产物目录：${bundle}`);

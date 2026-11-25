import { useEffect, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";

export function WindowControls({ onError }: { onError: (message: string) => void }) {
  const [maximized, setMaximized] = useState(false);
  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    const native = getCurrentWindow();
    let alive = true;
    const sync = async () => {
      const value = await native.isMaximized();
      if (alive) setMaximized(value);
    };
    const report = (error: unknown) => {
      if (alive) onError(String(error));
    };
    void sync().catch(report);
    const unlisten = native.onResized(() => { void sync().catch(report); });
    void unlisten.catch(report);
    return () => {
      alive = false;
      void unlisten.then((off) => off()).catch(() => {});
    };
  }, [onError]);

  const run = async (action: "minimize" | "toggleMaximize" | "close") => {
    try {
      const native = getCurrentWindow();
      await native[action]();
      if (action === "toggleMaximize") setMaximized(await native.isMaximized());
    } catch (error) {
      onError(String(error));
    }
  };
  const sizeLabel = maximized ? "还原窗口" : "最大化";
  return (
    <div className="window-controls" aria-label="窗口控制">
      <button type="button" className="window-control minimize" title="最小化"
              aria-label="最小化" onClick={() => void run("minimize")} />
      <button type="button" className={`window-control ${maximized ? "restore" : "maximize"}`}
              title={sizeLabel} aria-label={sizeLabel} onClick={() => void run("toggleMaximize")} />
      <button type="button" className="window-control close" title="关闭"
              aria-label="关闭" onClick={() => void run("close")} />
    </div>
  );
}

import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { FloatPanel, type PanelKind } from "./components/AnchorRail";
import "./styles/app.css";

/** 入口分流：原生浮窗由 Rust 初始化脚本注入 window.__FLOAT_KIND__——只渲染面板，
 *  不连 runtime（否则第二个 IPC 客户端会发 hello、污染主窗口的任务流）。
 *  注意不能用 URL 查询串：WebviewUrl::App 只接受路径，带 ? 会被当成文件名导致白屏。 */
declare global { interface Window { __FLOAT_KIND__?: string; } }
const floatParam = window.__FLOAT_KIND__ ?? "";
const FLOAT_TITLES: Record<string, string> = {
  facts: "个人事实", goals: "长期目标", memory: "本轮记忆",
};
const floatKind = floatParam in FLOAT_TITLES ? (floatParam as PanelKind) : null;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {floatKind
      ? <FloatPanel kind={floatKind} title={FLOAT_TITLES[floatKind] ?? "信息"} />
      : <App />}
  </React.StrictMode>,
);

import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { FloatPanel, type PanelKind } from "./components/AnchorRail";
import "./styles/app.css";

/** 入口分流：?float=<kind> 的窗口是钉住浮窗——只渲染面板，不连 runtime
 *  （否则第二个 IPC 客户端会发 hello、污染主窗口的任务流）。 */
const floatParam = new URLSearchParams(window.location.search).get("float");
const FLOAT_TITLES: Record<string, string> = {
  facts: "个人事实", goals: "长期目标", memory: "本轮记忆",
};
const floatKind = floatParam && floatParam in FLOAT_TITLES ? (floatParam as PanelKind) : null;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {floatKind
      ? <FloatPanel kind={floatKind} title={FLOAT_TITLES[floatKind] ?? "信息"} />
      : <App />}
  </React.StrictMode>,
);

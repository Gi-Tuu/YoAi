/** 性能基准：模拟 50/200/1000/10000 事件，测量纯前端处理延迟（不依赖 Tauri）。
 *  运行：npx vitest run tests/bench_events.ts，或 node 直接看输出。
 *  注意：以下为真实测量的钩子；具体数值以运行输出为准，不把目标写成结论。
 */

import { describe, it, expect } from "vitest";
import { ProcessPanel } from "../src/components/ProcessPanel";
import { render } from "@testing-library/react";
import type { ProcEvent } from "../src/hooks/useTaskStream";
import React from "react";

function mkEvents(n: number): ProcEvent[] {
  return Array.from({ length: n }, (_, i) => ({
    seq: i,
    name: i % 3 === 0 ? "tool_call" : i % 3 === 1 ? "tool_result" : "strategy_selected",
    data: { tool: `tool_${i % 17}`, result: "x".repeat(80), strategy: "react" },
    at: i,
  }));
}

const SCENARIOS = [50, 200, 1000, 10000];

describe("事件规模基准（虚拟化 + 默认折叠）", () => {
  for (const n of SCENARIOS) {
    it(`${n} 条事件：默认折叠时 DOM 节点数与渲染耗时`, () => {
      const events = mkEvents(n);
      const t0 = performance.now();
      const { container, unmount } = render(React.createElement(ProcessPanel, { events, thinking: "" }));
      const elapsed = performance.now() - t0;
      const domRows = container.querySelectorAll(".proc-row").length;
      // 关键断言：默认折叠下 DOM 行数与 n 无关（只显示摘要）
      expect(domRows).toBe(0);
      console.log(`[bench] n=${n} 折叠渲染=${elapsed.toFixed(1)}ms DOM行=${domRows}`);
      unmount();
    });
  }

  it("长文本持续输出：10k 字符快路径不抛错", () => {
    const events = mkEvents(1000);
    const { unmount } = render(React.createElement(ProcessPanel, {
      events, thinking: "分析".repeat(5000),
    }));
    unmount();
    expect(true).toBe(true);
  });
});

/** 星球系页：进化档案可视化（对齐旧 PySide6 端 GalaxyView）。
 *  恒星=根节点 · 行星=专家 · 同心轨道=血统深度 · 光晕色=生命周期。
 *  纯 SVG 实现，点击星球查看详情卡。 */

import { useCallback, useEffect, useState } from "react";
import { ipc } from "../lib/ipc";
import type { ArchiveNode } from "../types/ipc";

const W = 760;
const H = 520;
const CX = W / 2;
const CY = H / 2;

/** 生命周期 → 填充色（纸墨主题语义，对齐旧端 Palette）。 */
function lifecycleColor(lc: string): string {
  switch (lc) {
    case "active": return "var(--vermilion)";
    case "probation": return "var(--warn)";
    case "candidate": return "var(--weak)";
    case "retired": return "var(--rule)";
    default: return "var(--dim)";
  }
}

interface Positioned {
  node: ArchiveNode;
  x: number;
  y: number;
  r: number;
  ring: boolean;
}

function layout(nodes: ArchiveNode[]): { planets: Positioned[]; maxDepth: number } {
  const maxDepth = nodes.reduce((m, n) => Math.max(m, n.depth), 0);
  const base = Math.min(W, H) * 0.10;
  const gap = (Math.min(W, H) * 0.30) / Math.max(1, maxDepth);
  const byDepth = new Map<number, ArchiveNode[]>();
  for (const n of nodes) {
    const list = byDepth.get(n.depth) ?? [];
    list.push(n);
    byDepth.set(n.depth, list);
  }
  const planets: Positioned[] = [];
  for (const [depth, list] of [...byDepth.entries()].sort((a, b) => a[0] - b[0])) {
    const radius = base + gap * depth;
    list.forEach((node, i) => {
      if (depth === 0) {
        planets.push({ node, x: CX, y: CY, r: 34, ring: true });
        return;
      }
      const angle = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(1, list.length);
      planets.push({
        node,
        x: CX + radius * Math.cos(angle),
        y: CY + radius * Math.sin(angle) * 0.78,
        r: Math.max(12, 22 - depth * 2),
        ring: false,
      });
    });
  }
  return { planets, maxDepth };
}

export function GalaxyPage() {
  const [nodes, setNodes] = useState<ArchiveNode[]>([]);
  const [sel, setSel] = useState<ArchiveNode | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    setLoading(true);
    void ipc.getArchive();
  }, []);

  useEffect(() => {
    const off = ipc.onMessage((m) => {
      if (m.type === "archive.state") {
        setNodes(m.nodes);
        setLoading(false);
        setSel((prev) => (prev ? m.nodes.find((n) => n.id === prev.id) ?? null : null));
      }
    });
    void ipc.getArchive();
    return () => { off(); };
  }, []);

  const { planets, maxDepth } = layout(nodes);
  const base = Math.min(W, H) * 0.10;
  const gap = (Math.min(W, H) * 0.30) / Math.max(1, maxDepth);

  return (
    <div className="galaxy-page">
      <div className="galaxy-canvas-wrap">
        <svg className="galaxy-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet">
          {/* 轨道（虚线椭圆） */}
          {Array.from({ length: maxDepth }, (_, i) => {
            const r = base + gap * (i + 1);
            return (
              <ellipse key={i} cx={CX} cy={CY} rx={r} ry={r * 0.78}
                       className="galaxy-orbit" />
            );
          })}
          {/* 无节点时画淡淡的核心 */}
          {planets.length === 0 && (
            <circle cx={CX} cy={CY} r={20} className="galaxy-star" opacity={0.3} />
          )}
          {/* 星球 */}
          {planets.map(({ node, x, y, r, ring }) => (
            <g key={node.id} transform={`translate(${x},${y})`}
               className={`galaxy-planet lc-${node.lifecycle} ${sel?.id === node.id ? "selected" : ""}`}
               onClick={() => setSel(node)} role="button" tabIndex={0}>
              {node.lifecycle === "active" && (
                <circle r={r + 7} className="galaxy-glow" />
              )}
              <circle r={r} className="galaxy-body" fill={lifecycleColor(node.lifecycle)} />
              {ring && <ellipse rx={r + 13} ry={(r + 13) * 0.32} className="galaxy-ring" />}
              <text y={r + 13} className="galaxy-label">{node.name}</text>
            </g>
          ))}
        </svg>
        <button className="ghost galaxy-refresh" onClick={refresh}>
          {loading ? "载入中…" : "↻ 刷新星图"}
        </button>
      </div>

      <aside className="galaxy-detail">
        <div className="comms-label">节点详情</div>
        {!sel && <div className="side-empty">点击一颗星球查看专家节点详情…</div>}
        {sel && (
          <div className="node-detail">
            <div className="node-line"><b>{sel.name}</b></div>
            <div className="node-line">ID：{sel.id}　版本：v{sel.version}</div>
            <div className="node-line">生命周期：<span className={`lc lc-${sel.lifecycle}`}>{sel.lifecycle}</span></div>
            <div className="node-line">父节点：{sel.parent_id || "（根节点）"}</div>
            <div className="node-line">能力标签：{sel.capability_tags.join("、") || "（无）"}</div>
            <div className="node-line">工具白名单：{sel.tools.join("、") || "（无）"}</div>
            <div className="node-line">策略偏好：{sel.strategy_bias || "（默认）"}</div>
            <div className="node-line">模型档位：{sel.model_tier || "（默认）"}</div>
            <div className="node-line">修改差异：{sel.diff || "（无）"}</div>
            <div className="node-line">证据条数：{sel.evidence_count}</div>
            <div className="node-line">创建时间：{sel.created_at || "—"}</div>
            {sel.prompt_suffix && <div className="node-line">能力提示：{sel.prompt_suffix}</div>}
          </div>
        )}
        <div className="galaxy-legend">
          生命周期：● <span className="lc lc-active">active 运行中</span> ·
          ● <span className="lc lc-probation">probation 试用</span> ·
          ● <span className="lc lc-candidate">candidate 候选</span> ·
          ● <span className="lc lc-retired">retired 已退役</span>
        </div>
        <div className="galaxy-sub">恒星=根节点 · 行星=专家 · 轨道=血统 · 光晕=生命周期</div>
      </aside>
    </div>
  );
}

/** 星球系页：进化档案可视化（对齐旧 PySide6 端 GalaxyView）。
 *  恒星=根节点 · 行星=专家 · 同心轨道=血统深度 · 光晕色=生命周期。
 *  纯 SVG 实现，点击星球查看详情卡。 */

import { useCallback, useEffect, useState } from "react";
import { ipc } from "../lib/ipc";
import type { ArchiveNode, TrialRecordMsgData, TrialReportMsgData } from "../types/ipc";

const W = 760;
const H = 520;
const CX = W / 2;
const CY = H / 2;

/** 生命周期 → 填充色（纸墨主题语义，对齐旧端 Palette）。 */
function lifecycleColor(lc: string): string {
  switch (lc) {
    case "active": return "var(--lc-active)";
    case "probation": return "var(--lc-probation)";
    case "candidate": return "var(--lc-candidate)";
    case "retired": return "var(--lc-retired)";
    default: return "var(--dim)";
  }
}

function primaryTag(node: ArchiveNode): string {
  try {
    const parsed = JSON.parse(node.diff || "{}");
    if (parsed && typeof parsed.tag === "string" && parsed.tag) return parsed.tag;
  } catch { /* diff 可能是普通文本 */ }
  return node.capability_tags.find((t) => t !== "root") || node.capability_tags[0] || "general";
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
  const [notice, setNotice] = useState("");
  const [trial, setTrial] = useState<TrialRecordMsgData | null>(null);
  const [trialReport, setTrialReport] = useState<TrialReportMsgData | null>(null);

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
      if (m.type === "rsi.validated") {
        setNotice(`验证结论：${m.validation.verdict} · ${m.validation.note}`);
      }
      if (m.type === "trial.state") {
        setTrial(m.trial);
        if (m.trial.status === "running") setNotice(`试用已开始：${m.trial.scope}`);
      }
      if (m.type === "trial.report") {
        setTrialReport(m.report);
        setNotice(m.report.passed ? "试用硬门槛通过，可申请批准" : `未通过：${m.report.reason}`);
      }
      if (m.type === "rsi.rolled_back") {
        setNotice(`已回滚 ${m.decision.node_id}：${m.decision.reason}`);
      }
      if (m.type === "approval.recorded") {
        setNotice(`审批已记录：${m.decision.from_state} → ${m.decision.to_state}`);
      }
      if (m.type === "rsi.promoted") {
        const d = m.decision;
        setNotice(d.changed
          ? `晋升：${d.from_state} → ${d.to_state} · ${d.reason}`
          : `未晋升：${d.reason}`);
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
        {notice && <div className="boundary-notice">{notice}</div>}
        <div className="comms-label">节点详情</div>
        {!sel && <div className="side-empty">点击一颗星球查看专家节点详情…</div>}
        {sel && (
          <div className="node-detail">
            <div className="node-line"><b>{sel.name}</b></div>
            <div className="node-line">ID：{sel.id}　版本：v{sel.version}</div>
            <div className="node-line">生命周期：<span className={`lc lc-${sel.lifecycle}`}>{sel.lifecycle}</span></div>
            {sel.lifecycle === "candidate" && (
              <button type="button" className="boundary-trigger"
                      title="用 held-out validation 证据做 child/parent 成对验证；不晋升"
                      onClick={() => void ipc.validateCandidate(sel.id)}>
                验证候选
              </button>
            )}
            {sel.lifecycle === "probation" && (
              <div className="evo-trial-actions">
                <button type="button" className="boundary-trigger"
                        title="在当前能力标签上开启受控试用"
                        onClick={() => void ipc.startTrial(sel.id, `tag:${primaryTag(sel)}`, 20)}>
                  开始试用
                </button>
                {trial?.node_id === sel.id && (
                  <>
                    <button type="button" className="boundary-trigger"
                            onClick={() => void ipc.trialReport(trial.id)}>
                      查看试用报告
                    </button>
                    <button type="button" className="boundary-trigger"
                            disabled={!trialReport?.passed}
                            onClick={() => void ipc.approveActive(trial.id, "本机所有者", "人工批准")}>
                      批准晋升 active
                    </button>
                    <button type="button" className="boundary-trigger"
                            onClick={() => void ipc.rejectTrial(trial.id, "人工拒绝")}>
                      拒绝退役
                    </button>
                  </>
                )}
              </div>
            )}
            {trialReport?.node_id === sel.id && (
              <div className="evo-report">
                <div>试用样本：子 {trialReport.child_samples} / 父 {trialReport.parent_samples}</div>
                <div>成功率：{(trialReport.child_rate * 100).toFixed(1)}% / 父 {(trialReport.parent_rate * 100).toFixed(1)}%</div>
                <div>返工率：{(trialReport.child_rework * 100).toFixed(1)}% / 父 {(trialReport.parent_rework * 100).toFixed(1)}%</div>
                <div>成本：{trialReport.child_tokens} / 父 {trialReport.parent_tokens} token</div>
                <div>{trialReport.reason}</div>
              </div>
            )}
            <div className="node-line">父节点：{sel.parent_id || "（根节点）"}</div>
            <div className="node-line">能力标签：{sel.capability_tags.join("、") || "（无）"}</div>
            <div className="node-line">工具白名单：{sel.tools.join("、") || "（无）"}</div>
            <div className="node-line">策略偏好：{sel.strategy_bias || "（默认）"}</div>
            <div className="node-line">模型档位：{sel.model_tier || "（默认）"}</div>
            <div className="node-line">修改差异：{sel.diff || "（无）"}</div>
            <div className="node-line">证据条数：{sel.evidence_count}</div>
            {(sel.reports?.length ?? 0) > 0 && (
              <div className="evo-reports">
                <div className="comms-label">进化审计</div>
                {sel.reports!.map((report) => (
                  <div key={report.id} className="evo-report">
                    <div>{report.created_at} · {report.cause} · {report.triggered ? "已尝试" : "未触发"}</div>
                    <div>{report.reason}</div>
                    {report.promotion && (
                      <div>晋升：{report.promotion.promoted ? "是" : "否"} — {report.promotion.reason}</div>
                    )}
                    {report.promotion?.report && (
                      <div className="evo-boundaries">
                        结论：{report.promotion.report.verdict} · 样本 {report.promotion.report.total_samples}
                        {report.promotion.report.boundaries.map((b) => (
                          <div key={b.capability_tag}>
                            {b.capability_tag}：子 {b.node_rate.toFixed(2)}
                            [{b.node_ci.map((v) => v.toFixed(2)).join(",")}] / 父 {b.parent_rate.toFixed(2)}
                            [{b.parent_ci.map((v) => v.toFixed(2)).join(",")}]
                            {b.sample_enough ? "" : " · 样本不足"}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
            {sel.lifecycle === "active" && (
              <button type="button" className="boundary-trigger"
                      title="检查近 30 天是否退化；命中则自动退役并回退父节点"
                      onClick={() => void ipc.checkRollback(sel.id)}>
                检查回滚
              </button>
            )}
            {(sel.evidence?.length ?? 0) > 0 && (
              <div className="evo-evidence">
                <div className="comms-label">证据索引</div>
                {sel.evidence!.slice(-8).map((e) => (
                  <div key={e.id} className="evo-evidence-row">
                    {e.kind} · {e.outcome} · {e.task_fingerprint || "无指纹"}
                  </div>
                ))}
              </div>
            )}
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

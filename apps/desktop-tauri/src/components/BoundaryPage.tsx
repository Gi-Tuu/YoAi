/** RSI R1 看板 + R2.1 shadow 触发：候选不进路由、不自动生效。 */

import { useCallback, useEffect, useState } from "react";
import { ipc } from "../lib/ipc";
import type { BoundaryRow, BoundaryStateMsg } from "../types/ipc";

const STATUS_LABEL: Record<BoundaryRow["status"], string> = {
  healthy: "健康", watch: "观察", weak: "薄弱", insufficient: "样本不足",
};

export function BoundaryPage() {
  const [report, setReport] = useState<BoundaryStateMsg["report"] | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");

  const refresh = useCallback(() => {
    setLoading(true);
    void ipc.getBoundary();
  }, []);

  useEffect(() => {
    const off = ipc.onMessage((m) => {
      if (m.type === "boundary.state") {
        setReport(m.report);
        setLoading(false);
      }
      if (m.type === "rsi.triggered") {
        const made = m.decisions.filter((d) => d.created).length;
        const reason = m.decisions.find((d) => !d.created)?.reason ?? "";
        setNotice(made
          ? `已生成 ${made} 个 shadow 候选（未进路由，待隔离验证）`
          : `未生成候选：${reason || "当前边界不满足触发条件"}`);
      }
    });
    refresh();
    return off;
  }, [refresh]);

  const rows = report?.rows ?? [];
  const weak = rows.filter((r) => r.status === "weak").length;
  const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

  return (
    <div className="boundary-page">
      <header className="boundary-head">
        <div>
          <h2>能力边界看板</h2>
          <p>近 {report?.window_days ?? 30} 天 · 真实执行证据 + 用户反馈 · 候选只进 shadow，不自动生效</p>
        </div>
        <button type="button" onClick={refresh}>{loading ? "载入中…" : "↻ 刷新"}</button>
      </header>

      {notice && <div className="boundary-notice">{notice}</div>}
      <div className="boundary-summary">
        <div className="boundary-stat"><span>样本数</span><b>{report?.total ?? 0}</b></div>
        <div className="boundary-stat"><span>成功率</span><b>{pct(report?.success_rate ?? 0)}</b></div>
        <div className="boundary-stat"><span>返工率</span><b>{pct(report?.rework_rate ?? 0)}</b></div>
        <div className="boundary-stat"><span>薄弱边界</span><b>{weak}</b></div>
      </div>

      {rows.length === 0 ? (
        <div className="boundary-empty">
          还没有能力边界数据。完成任务并产生用户反馈后，这里会按能力标签点亮。
        </div>
      ) : (
        <div className="boundary-table-wrap">
          <table className="boundary-table">
            <thead>
              <tr>
                <th>能力标签</th><th>样本</th><th>成功率 / Wilson 区间</th>
                <th>返工率</th><th>平均 token</th><th>正向</th><th>相对基线</th><th>状态</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const ciLow = row.success_ci[0] ?? 0;
                const ciHigh = row.success_ci[1] ?? 0;
                return (
                  <tr key={row.tag}>
                    <td className="boundary-tag">{row.tag}</td>
                    <td>{row.total}</td>
                    <td>
                      <div className="boundary-bar" title={`${pct(ciLow)}–${pct(ciHigh)}`}>
                        <span style={{ width: `${row.success_rate * 100}%` }} />
                        <i style={{ left: `${ciLow * 100}%` }} />
                        <i style={{ left: `${ciHigh * 100}%` }} />
                      </div>
                      <small>{pct(row.success_rate)} · [{pct(ciLow)}, {pct(ciHigh)}]</small>
                    </td>
                    <td>{pct(row.rework_rate)}</td>
                    <td>{row.avg_tokens.toLocaleString("zh-CN")}</td>
                    <td>{row.positive}</td>
                    <td className={row.baseline_gap < 0 ? "boundary-neg" : "boundary-pos"}>
                      {row.baseline_gap >= 0 ? "+" : ""}{(row.baseline_gap * 100).toFixed(1)}pp
                    </td>
                    <td>
                      <span className={`boundary-status st-${row.status}`}>
                        {STATUS_LABEL[row.status]}
                      </span>
                      {row.status === "weak" && (
                        <button type="button" className="boundary-trigger"
                                title="生成 shadow 候选；不进路由、不自动生效"
                                onClick={() => void ipc.triggerRsi([row.tag])}>
                          生成候选
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="boundary-note">
        状态规则：样本 &lt; 20 不下结论；返工率 ≥15% 进观察、≥25% 进薄弱；
        成功率 Wilson 上界低于基线 10pp 以上也进薄弱。看板不触发任何进化行为。
      </p>
    </div>
  );
}

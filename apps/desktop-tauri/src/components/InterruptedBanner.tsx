/** 上次被打断的对话轮次（S5-2）。
 *
 *  Core 没有断点续跑，所以这里不假装"从中间继续"：只提供**用同样的输入重新发送**，或忽略。
 *  - 在原会话里：「重新发送」；
 *  - 在别的会话里：先「切到该会话」；
 *  - 输入太长（被截断）：只能手动重发。
 */

import type { InterruptedTurn } from "../types/ipc";

const pad = (n: number) => String(n).padStart(2, "0");

function when(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function preview(text: string): string {
  const one = text.replace(/\s+/g, " ").trim();
  return one.length > 60 ? `${one.slice(0, 60)}…` : one;
}

export function InterruptedBanner({ items, currentSessionId, busy, onResend, onSwitch, onDismiss }: {
  items: InterruptedTurn[];
  currentSessionId: string;
  busy: boolean;
  onResend: (item: InterruptedTurn) => void;
  onSwitch: (sessionId: string) => void;
  onDismiss: (runId: string) => void;
}) {
  if (items.length === 0) return null;
  return (
    <div className="interrupted-banner" role="status" aria-label="上次被中断的对话">
      {items.slice(0, 3).map((item) => {
        const here = item.session_id === currentSessionId;
        return (
          <div key={item.run_id} className="interrupted-item">
            <div className="interrupted-text">
              <b>上次被中断</b>
              <span className="interrupted-dim">
                {when(item.started_at)}{!here && item.session_name ? ` · 「${item.session_name}」` : ""}
              </span>
              <span className="interrupted-input">「{preview(item.input)}」</span>
              {item.truncated && <span className="interrupted-dim">内容太长，请手动重新发送</span>}
            </div>
            <div className="interrupted-actions">
              {!item.truncated && here && (
                <button type="button" disabled={busy} onClick={() => onResend(item)}>重新发送</button>
              )}
              {!item.truncated && !here && (
                <button type="button" onClick={() => onSwitch(item.session_id)}>
                  切到「{item.session_name || "原会话"}」
                </button>
              )}
              <button type="button" onClick={() => onDismiss(item.run_id)}>忽略</button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

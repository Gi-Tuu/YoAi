/** 产物 / 文件改动卡片（对齐主流 IDE Agent 的 change set UI）。
 *  - 产物：新建文件，可预览/下载（图1）
 *  - 改动：已有文件修改，逐文件 +X/-Y，点击开展行级 diff（图2）
 *  数据来自 snapshot.artifacts / snapshot.changes 与 file.changed 事件。 */

import { useState } from "react";
import type { FileChangeRecord, DiffOp } from "../types/ipc";

const nameOf = (path: string) => path.split(/[\\/]/).filter(Boolean).pop() || path;

function DiffView({ ops }: { ops: DiffOp[] }) {
  if (!ops?.length) return <div className="diff-empty">（无行级 diff 数据）</div>;
  return (
    <div className="diff-body">
      {ops.map((op, i) => (
        <div key={i} className={`diff-line diff-${op.kind}`}>
          <span className="diff-sign">{op.kind === "add" ? "+" : op.kind === "remove" ? "-" : " "}</span>
          <span className="diff-num">{op.new_line ?? op.old_line ?? ""}</span>
          <code className="diff-text">{op.text}</code>
        </div>
      ))}
    </div>
  );
}

function Row({ record }: { record: FileChangeRecord }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="change-row">
      <button className="change-row-head" onClick={() => setOpen((v) => !v)}
              aria-expanded={open} title={record.path}>
        <span className="change-name">{nameOf(record.path)}</span>
        <span className="change-stat">
          <span className="stat-add">+{record.added}</span>
          <span className="stat-remove">-{record.removed}</span>
        </span>
        <span className="change-arrow">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="change-detail">
          <div className="change-path">{record.path}</div>
          <DiffView ops={record.diff} />
        </div>
      )}
    </div>
  );
}

function download(record: FileChangeRecord) {
  const blob = new Blob([record.after ?? ""], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nameOf(record.path);
  a.click();
  URL.revokeObjectURL(url);
}

/** 产物列表：新建文件，可下载。 */
export function Artifacts({ records }: { records: FileChangeRecord[] }) {
  if (!records.length) return null;
  return (
    <section className="artifacts-panel" aria-label="产物">
      <div className="artifacts-head">产物 · {records.length}</div>
      {records.map((r) => (
        <div key={r.id} className="artifact-item">
          <span className="artifact-icon">▤</span>
          <span className="artifact-meta">
            <strong>{nameOf(r.path)}</strong>
            <small>{(r.after ?? "").length.toLocaleString()} 字符</small>
          </span>
          <button className="artifact-download" title="下载产物" onClick={() => download(r)}>↓</button>
        </div>
      ))}
    </section>
  );
}

/** 改动摘要：N 个文件已修改，逐文件 +X/-Y，点击开展行级 diff。 */
export function Changes({ records }: { records: FileChangeRecord[] }) {
  const [open, setOpen] = useState(false);
  if (!records.length) return null;
  const totalAdd = records.reduce((n, r) => n + (r.added || 0), 0);
  const totalRemove = records.reduce((n, r) => n + (r.removed || 0), 0);
  return (
    <section className="changes-panel" aria-label="文件改动">
      <button className="changes-head" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span>{records.length} 个文件已修改</span>
        <span className="changes-total">
          <span className="stat-add">+{totalAdd}</span>
          <span className="stat-remove">-{totalRemove}</span>
        </span>
        <span className="change-arrow">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="changes-list">
          {records.map((r) => <Row key={r.id} record={r} />)}
        </div>
      )}
    </section>
  );
}

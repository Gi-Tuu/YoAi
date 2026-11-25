/** 轻量模态对话框：输入 / 确认 / 单选。WebView2 下 window.prompt/confirm
 *  行为不可靠，统一用内联模态。 */

import { useEffect, useRef, useState } from "react";

interface ModalInputProps {
  title: string;
  placeholder?: string;
  initial?: string;
  onOk: (value: string) => void;
  onCancel: () => void;
}

export function ModalInput({ title, placeholder, initial = "", onOk, onCancel }: ModalInputProps) {
  const [value, setValue] = useState(initial);
  const ref = useRef<HTMLInputElement | null>(null);
  useEffect(() => { ref.current?.focus(); ref.current?.select(); }, []);
  return (
    <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="modal-card">
        <div className="modal-title">{title}</div>
        <input ref={ref} className="modal-input" value={value}
               placeholder={placeholder}
               onChange={(e) => setValue(e.target.value)}
               onKeyDown={(e) => {
                 if (e.key === "Enter" && value.trim()) onOk(value.trim());
                 if (e.key === "Escape") onCancel();
               }} />
        <div className="modal-actions">
          <button onClick={onCancel}>取消</button>
          <button className="primary" disabled={!value.trim()} onClick={() => onOk(value.trim())}>确定</button>
        </div>
      </div>
    </div>
  );
}

interface ModalConfirmProps {
  title: string;
  text: string;
  detail?: string;
  okLabel?: string;
  onOk: () => void;
  onCancel: () => void;
}

export function ModalConfirm({ title, text, detail, okLabel = "确定", onOk, onCancel }: ModalConfirmProps) {
  return (
    <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="modal-card">
        <div className="modal-title">{title}</div>
        <p className="modal-text">{text}</p>
        {detail && <p className="modal-detail">{detail}</p>}
        <div className="modal-actions">
          <button onClick={onCancel}>取消</button>
          <button className="danger" onClick={onOk}>{okLabel}</button>
        </div>
      </div>
    </div>
  );
}

interface ModalSelectProps {
  title: string;
  options: { value: string; label: string }[];
  onOk: (value: string) => void;
  onCancel: () => void;
}

export function ModalSelect({ title, options, onOk, onCancel }: ModalSelectProps) {
  return (
    <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="modal-card">
        <div className="modal-title">{title}</div>
        <div className="modal-options">
          {options.length === 0 && <div className="modal-text">（无可选项）</div>}
          {options.map((o) => (
            <button key={o.value} className="modal-option" onClick={() => onOk(o.value)}>{o.label}</button>
          ))}
        </div>
        <div className="modal-actions">
          <button onClick={onCancel}>取消</button>
        </div>
      </div>
    </div>
  );
}

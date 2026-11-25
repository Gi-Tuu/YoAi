/** 通讯页：单聊/群会话列表、消息线程、外部智能体接入。
 *  对齐旧 PySide6 端 ChatPanel 的全部交互：
 *  建群 / 拉人 / 双击外部智能体入群 / 发消息 / 历史加载。 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ipc } from "../lib/ipc";
import type { ChatEntry, ChatStateMsg, ConversationInfo } from "../types/ipc";
import { ModalInput, ModalSelect } from "./Dialog";

export function CommsPage() {
  const [state, setState] = useState<ChatStateMsg | null>(null);
  const [threads, setThreads] = useState<Record<string, ChatEntry[]>>({});
  const [target, setTarget] = useState("");
  const [input, setInput] = useState("");
  const [tip, setTip] = useState("");
  const [dialog, setDialog] = useState<
    | { kind: "newGroup" }
    | { kind: "addMember"; options: { value: string; label: string }[] }
    | null
  >(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const off = ipc.onMessage((m) => {
      if (m.type === "chat.state") {
        setState(m);
        if (m.history_target) {
          setThreads((prev) => ({ ...prev, [m.history_target as string]: m.history ?? [] }));
        }
      } else if (m.type === "chat.msg") {
        setThreads((prev) => ({
          ...prev,
          [m.target]: [...(prev[m.target] ?? []),
            { sender: m.sender, name: m.name, content: m.content, own: m.own }],
        }));
      }
    });
    void ipc.chatState();
    return () => { off(); };
  }, []);

  // 消息线程自动滚底
  const entries = threads[target] ?? [];
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [entries.length, target]);

  const select = useCallback((c: ConversationInfo) => {
    setTarget(c.id);
    void ipc.chatHistory(c.id);
  }, []);

  const send = useCallback(() => {
    const text = input.trim();
    if (!text || !target) return;
    void ipc.chatSend(target, text);
    setInput("");
  }, [input, target]);

  const current = state?.conversations.find((c) => c.id === target);
  const peers = (state?.conversations ?? []).filter((c) => c.kind === "peer");

  return (
    <div className="comms-page">
      <div className="comms-left">
        <div className="comms-label">会话</div>
        <div className="comms-list">
          {(state?.conversations ?? []).map((c) => (
            <button key={c.id}
                    className={`conv-item ${c.id === target ? "active" : ""}`}
                    title={`${c.kind === "peer" ? "单聊" : "群会话"} · ${c.id}`}
                    onClick={() => select(c)}>
              <span className="conv-mark">{c.kind === "peer" ? "●" : "◉"}</span>
              {c.kind === "peer" ? c.name : `${c.name} · ${c.members} 人`}
            </button>
          ))}
          {(state?.conversations ?? []).length === 0 && (
            <div className="side-empty">（还没有会话）</div>
          )}
        </div>
        <div className="comms-btns">
          <button onClick={() => setDialog({ kind: "newGroup" })}>建群</button>
          <button disabled={!current || current.kind !== "group"}
                  onClick={() => current && setDialog({
                    kind: "addMember",
                    options: peers.map((p) => ({ value: p.id, label: p.name })),
                  })}>拉人</button>
        </div>
        <div className="comms-label">外部智能体 · 双击加入当前群</div>
        <div className="comms-external">
          {(state?.external ?? []).map((e) => (
            <button key={e.name} className="conv-item ext"
                    title={`${e.name} · ${e.level}\n可用：${e.available}`}
                    onDoubleClick={() => {
                      if (!current || current.kind !== "group") {
                        setTip("请先选择一个群会话，再双击加入");
                        return;
                      }
                      void ipc.chatAddExternal(current.id, e.name);
                      setTip(`${e.name} 已处理`);
                    }}>
              <span className={`ext-mark ${e.available ? "on" : ""}`}>{e.available ? "✓" : "—"}</span>
              [{e.level}] {e.name}
            </button>
          ))}
          {(state?.external ?? []).length === 0 && (
            <div className="side-empty">（没有外部智能体）</div>
          )}
        </div>
      </div>

      <div className="comms-right">
        <div className="comms-target">{current ? current.name : "选择一个会话"}</div>
        <div className="comms-scroll" ref={scrollRef}>
          {entries.length === 0 && (
            <div className="side-empty">{target ? "还没有消息，发一条吧。" : "选择会话后开始聊天…"}</div>
          )}
          {entries.map((e, i) => (
            <div key={i} className={`comms-msg ${e.own ? "own" : ""}`}>
              <div className="comms-name">{e.name}</div>
              <div className="comms-bubble">{e.content}</div>
            </div>
          ))}
        </div>
        {tip && <div className="comms-tip">{tip}</div>}
        <div className="comms-input-row">
          <input className="comms-input" value={input} placeholder="输入消息，回车发送…"
                 disabled={!target}
                 onChange={(e) => setInput(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); send(); } }} />
          <button className="primary" disabled={!target || !input.trim()} onClick={send}>发送</button>
        </div>
      </div>

      {dialog?.kind === "newGroup" && (
        <ModalInput title="建群" placeholder="群名称"
                    onCancel={() => setDialog(null)}
                    onOk={(name) => { void ipc.chatNewGroup(name); setDialog(null); setTip(`已建群：${name}`); }} />
      )}
      {dialog?.kind === "addMember" && (
        <ModalSelect title="拉人（选择智能体）" options={dialog.options}
                     onCancel={() => setDialog(null)}
                     onOk={(peerId) => {
                       if (current) void ipc.chatAddMember(current.id, peerId);
                       setDialog(null); setTip("已处理");
                     }} />
      )}
    </div>
  );
}

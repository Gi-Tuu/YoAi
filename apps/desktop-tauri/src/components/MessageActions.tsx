/** 消息动作条：按消息归属显示，不把智能体专属动作混给用户消息。 */

interface Props {
  role: "user" | "assistant";
  busy?: boolean;
  onCopy: () => void;
  onShare: () => void;
  onEdit?: () => void;
  onRetract?: () => void;
  onRegenerate?: () => void;
  onFeedback?: (kind: string) => void;
}

export function MessageActions({ role, busy, onCopy, onShare,
  onEdit, onRetract, onRegenerate, onFeedback }: Props) {
  const act = (kind: string, fn: () => void) => () => {
    onFeedback?.(kind);
    fn();
  };
  return (
    <div className="message-actions" aria-label="消息操作">
      <button type="button" title="复制这条消息" onClick={act("copy", onCopy)}>复制</button>
      {role === "user" && onEdit && (
        <button type="button" title="编辑这条提问并从这里重发" onClick={act("edit", onEdit)}>编辑</button>
      )}
      {role === "user" && onRetract && (
        <button type="button" title="撤回这条提问及其回答" onClick={act("retract", onRetract)}>撤回</button>
      )}
      {role === "assistant" && onRegenerate && (
        <button type="button" title="重新生成这条回答" disabled={busy}
                onClick={act("regenerate", onRegenerate)}>重新生成</button>
      )}
      <button type="button" title="导出这条消息" onClick={act("share", onShare)}>分享</button>
    </div>
  );
}

/** Markdown 渲染：react-markdown + remark-gfm（表格）+ rehype-highlight（代码高亮）。
 *  长流式文本：未完成时按纯文本快渲染，完成后才做完整 markdown 格式化（任务 §7.8）。
 */

import { memo, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1200); }
    catch { /* 剪贴板不可用时静默 */ }
  };
  return (
    <div className="code-block">
      <div className="code-head">
        <span>{lang || "code"}</span>
        <button onClick={copy}>{copied ? "已复制" : "复制"}</button>
      </div>
      <pre><code>{code}</code></pre>
    </div>
  );
}

interface Props { text: string; streaming?: boolean; }

export const Markdown = memo(function Markdown({ text, streaming = false }: Props) {
  // 流式且过长：快路径纯文本（避免每 token 重跑 remark 解析树）
  const fastPath = streaming && text.length > 4000;
  const body = useMemo(() => {
    if (fastPath) return <pre className="stream-raw">{text}</pre>;
    return (
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className ?? "");
            const raw = String(children ?? "");
            if (match || raw.includes("\n")) {
              return <CodeBlock lang={match?.[1] ?? ""} code={raw.replace(/\n$/, "")} />;
            }
            return <code className={className} {...props}>{children}</code>;
          },
        }}
      >{text}</ReactMarkdown>
    );
  }, [text, fastPath]);
  return <div className="md-body">{body}</div>;
});

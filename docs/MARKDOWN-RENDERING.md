# 对话区 Markdown 渲染（2026-11-24）

## 现象

桌面端里对方（YoAi/peer）返回的 Markdown 内容显示成原始文本——
`**加粗**`、`- 列表`、代码块、链接都没渲染。

## 根因

`src/yoai/desktop/widgets.py` 的 `ChatView._agent_html()` 与
`ChatTranscript._render()` 把整段消息用 `_esc()`（html.escape）转义后
直接塞进 HTML，Markdown 语法字符被原样转义成文本。这是安全方向的正确做法
（防模型输出注入 HTML），但少了"转义后解析 Markdown"这一步。

## 修复

新增 `src/yoai/desktop/markdown_html.py`：轻量 Markdown→HTML 转换器
（纯标准库、无第三方依赖、exe 不增重）。

- **先整体 html.escape(quote=True)，再解析**：所有分支处理的都是安全文本，
  `<script>` / `onerror=` 绝无可能变成真实标签；
- 块级：标题（`#`–`######`）、有序/无序列表、代码块（三反引号，内部不解析 md）、
  水平线（`---`）、段落（段内换行 `<br>`）；
- 行内：粗体 `**`、斜体 `*`、行内代码 `` ` ``、链接 `[text](url)`；
- 链接**只认 http/https**，`file://` / `javascript:` 降级为纯文本；
- 用到的颜色由调用方传入（`link_color=palette.brick`），跟随主题切换。

接入点：

- `ChatView._agent_html()`：assistant 消息走 `md_to_html()`；
- `ChatTranscript._render()`：`own=False`（对方）走 `md_to_html()`，
  自己的输入仍走 `_esc()` 纯文本——**用户输入不被当 Markdown 渲染**，避免误解和注入。

## 验证

`tests/test_markdown_render.py` 10 项：纯文本、粗斜体/行内码、标题/列表、
代码块保真、链接协议白名单、HTML 注入转义、水平线，以及 3 项 Qt
offscreen 集成（两个视图真渲染 + 用户消息保持纯文本）。
全量 **276 passed**。

## 注意

- 历史消息重新打开时会按新逻辑渲染（历史存的是原文，不是渲染后的 HTML）；
- QTextBrowser 会把 `<strong>` 规范化成 `span style="font-weight:600"`，
  视觉表现一致——测试按 Qt 实际输出断言，不要反向改回去。

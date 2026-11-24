# 给 Core 的需求清单（2026-11-24）

> 背景：YoAi 今天排查了 8 个生产问题，其中 **7 个已在 YoAi 侧解决、不需要 Core 改**，
> 只有 1 个（思考块回传）确实需要 Core 支持。文档按优先级分三节，请只处理第一节，
> 第二节是"建议评估"，第三节列出不用改的部分——避免做无用功。

---

## 一、真需要 Core 更新的（P1）：thinking / signature 块回传

### 问题

Anthropic 协议（DeepSeek Anthropic 兼容端点也遵循）在 thinking 模式下要求：
**上一轮 assistant 消息里的 `thinking` 块和 `signature` 必须原样回传**，
否则下一轮请求返回 400：

```
The `content[].thinking` in the thinking mode must be passed back to the API.
```

### Core 现状（已核实代码）

- `src/yai_core/llm/anthropic.py:207` 的注释明确写着：
  「Anthropic 响应 → ModelResponse；非文本/非 tool_use 的块（如思考块）**忽略但保留 raw**」
- `ModelResponse.raw` 确实保存了完整原始响应（`anthropic.py:252`：`raw=response`）
- **但是** `kernel/loop.py:_append_assistant_tool_calls()` 构造下一轮 assistant 消息时
  只写 `content` + `tool_calls`，**从不读 `raw`** → thinking / signature 永久丢失

### 需求

让 `ModelResponse.raw` 中保留的非文本块（至少 `thinking` 与 `signature`）在下一轮
构造 assistant 消息时能被原样带回给模型 provider。

建议形态（供参考，Core 自行定）：
1. `ChatMessage` 增加一个可选字段承载"provider 原始内容块"（如 `raw_content_blocks`），
   默认空、对现有 provider 零影响；
2. `_append_assistant_tool_calls` 把 `resp.raw` 里的 thinking/signature 块填进去；
3. provider 构造请求时（Core 自己的 `llm/anthropic.py` 或宿主适配器）读取该字段，
   放进 assistant 的 content blocks。

### 为什么 YoAi 侧修不了

raw 信息虽然存在，但 Core 的上下文对象（`Context.messages`）里根本没有承载它的字段，
YoAi 的 provider 只能看到 Core 传下来的 OpenAI 线格式消息——**信息在 Core 侧被丢弃，
适配层补不回来**。这正是"内核可以改但要能跟 Core 更新"约定下，适合放进 Core 的改动：
一次改动，所有 Anthropic 系 provider 都受益。

### 影响面

- 只在 thinking 模式 + 多轮工具调用时触发；不开 thinking 完全无感
- 默认字段为空 = 行为逐字节不变（向后兼容）

---

## 二、建议 Core 评估的（P2，非阻塞，YoAi 已有 workaround）

### 2.1 DIRECT 策略与工具 schema 的矛盾

`_ACTION_HINTS` 词表漏词（如"记住"、"写文件"）→ 任务被判 DIRECT → 不注入工具 schema，
但 system prompt 仍注入工具目录文本 → 模型把调用写成正文 DSML → Core 安全防线拒绝 →
用户看到静默失败。

YoAi 现状：继承公开 `AdaptiveRouter` 做"有工具就 REACT"绕过了。
建议 Core 评估：DIRECT 是否应在"宿主有工具"时默认注入 schema（让模型自己判断调不调），
或提供官方开关。这是词表方案的根治——穷举动词永远补不全。

### 2.2 过渡语被当最终答案

模型偶尔只输出"我去查一下"这类**行动承诺元话语**而不真的调工具，
Core 的 `if not resp.tool_calls` 把纯文本当最终答案 → 任务没执行就结束。

YoAi 现状：适配层检测到过渡语后自动 re-ask 一次。
建议 Core 评估：是否在 react 循环里提供"纯文本回合是否继续"的钩子/开关。

### 2.3 `CollectChannel.confirm()` 默认 `auto_confirm=True`

Core 默认的 `CollectChannel` 永远自动批准审批——宿主若只切 `AllowlistPolicy(auto)`
而不注入自己的 channel，审批形同虚设（启动还会打印 allow_all 警告让人误以为没配）。

YoAi 现状：注入自己的 `ApprovalChannel`。
建议 Core 评估：`auto_confirm` 默认改为 False（失败关闭），或在文档显著提示宿主必须替换。

---

## 三、不需要 Core 改的（YoAi 侧已解决，请忽略）

以下都是"Core 提供公开扩展点、YoAi 用对了"的案例，列出来只为说明边界，
**不需要 Core 做任何改动**：

| 问题 | YoAi 的解法 | 用的 Core 公开能力 |
|---|---|---|
| error 事件 UI 不可见 | 桌面端把 ERROR 显示在对话区 | 已有 ERROR 事件 |
| 实操工具缺失 | 文件读写 + 联网 | `filesystem_capabilities` / `filesystem_gate` / `build_spec` |
| 进程残留 | worker 真 cancel asyncio 任务 | QThread / Core 明确保护 CancelledError 传播 |
| 多实例 | QLocalSocket 单实例守卫 | 与 Core 无关 |
| 权限 3 档 | auto 档 + 审批弹窗 | `AllowlistPolicy` / `channel.confirm` |
| 全放行开关 | 环境变量切 allow_all | 同上 |
| **Anthropic tool_result 400** | 多 tool_result 合并到一条 user | **Core 自己的 `llm/anthropic.py:to_anthropic_messages` 已正确实现**——是我们早期重复造轮子，已改用 Core 官方实现 |

> 最后一条尤其重要：请 Core 负责人**不要**为此改代码——Core 的官方转换本来就是对的，
> 是 YoAi 之前自己写了一份有 bug 的转换。YoAi 已改为复用 Core 的官方实现（2026-11-24 当日清理）。

---

## 总结

| 优先级 | 项 | 谁改 |
|---|---|---|
| P1 | thinking / signature 块回传 | **Core**（唯一真需求） |
| P2 | DIRECT schema 矛盾 / 过渡语钩子 / CollectChannel 默认 | Core 评估（YoAi 有 workaround） |
| — | 其余 7 项 | 不需要 Core；YoAi 已解决或 plan 复用 Core 官方实现 |

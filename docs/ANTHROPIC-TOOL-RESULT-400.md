# Anthropic 网关 400：tool_use 没有紧随 tool_result（2026-11-24）

## 现象（生产截图）

```
[模型网关错误] HTTP 400: messages.3:`tool_use` ids were found without
`tool_result` blocks immediately after: call_01_RF28IhPMal2H0GOyjT7p5086.
Each `tool_use` block must have a corresponding `tool_result` block in the next m...
```

`tool_use` / `tool_result` 是 Anthropic 协议术语——说明当前走的是
`DeepSeekAnthropicAdapter`（讯飞 OpenAI 适配器不可用时 fallback）。

## 根因

Core 的消息序列（OpenAI 线格式）：
```
assistant(tool_calls × N)     ← 一条消息里 N 个工具调用
tool(结果A)                    ← N 条独立消息
tool(结果B)
```

`_openai_messages_to_anthropic` 原来把**每条** tool 消息转成**独立**的 user 消息：
```
assistant(tool_use A, tool_use B)
user(tool_result A)            ← Anthropic 要求同一批 result 在这"一条"里
user(tool_result B)
```
Anthropic 硬约束：assistant 一条消息里多个 tool_use，其 tool_result 必须在**紧接着的
一条** user 消息里全部给出。拆成多条就 400。**单工具调用不触发**——所以之前没暴露。

## 修复（`8ce7174`）

`_openai_messages_to_anthropic`：连续 tool 消息攒入 `pending_tool_results`，
遇到非 tool 消息（或序列结尾）flush 成**一条** user 消息，content 含多个 tool_result block。

验证：
- 4 个新测试：多工具合并 / 后续 user 不打断 / 单工具兼容 / 末尾 flush
- 真实 Anthropic 端点发"2 个 tool_use + 2 个 tool_result"payload：
  **原来的 tool_result 400 消失**（进入了下一个不同的错误，见下）
- 全量 228 passed

## 发现的下一个独立坑（本次未修，记录）

真实端点验证时，用**手工构造**的消息序列触发了新错误：

```
The `content[].thinking` in the thinking mode must be passed back to the API.
```

DeepSeek thinking 模式要求 assistant 的 thinking 块原样回传，但
`_extract_text` 跳过 thinking 块、Core 的 `_append_assistant_tool_calls`
只写 content + tool_calls——**thinking 块在 Core 侧就丢了，适配器补不回来**。

注意：这是我用手工序列触发的，与用户报的 400 是两个独立问题；
真实 Core 循环是否触发取决于适配器是否真的收到带 thinking 的历史。
若后续生产遇到，方向：
1. 换不带 thinking 的 `ANTHROPIC_MODEL`（治标、最快）
2. 用 `ModelResponse.raw` 保存原始 content blocks，在 YoAi 侧适配层把
   thinking/signature 原样注入回 assistant 消息（需改 Core 的消息构造或加扩展点）

## 与讯飞路径的关系

本机讯飞适配器 `available()` = True，`_build_main_model` 按顺序先取讯飞——
正常不会走 Anthropic。用户环境若讯飞配置失效（key/网络/环境变量覆盖），
才会 fallback 到 DeepSeek Anthropic 并踩到这个 bug。
两条路径都应正确，本次修的是 Anthropic 路径。

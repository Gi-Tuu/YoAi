# 真·流式输出（2026-11-24）

## 需求与结论

此前 Core 的 `achat` 用 SDK `messages.create()` 一次性返回，UI 只有最终结果出现——
看起来像卡住。本轮实现**每一轮模型输出都逐字流式显示**（包括多轮工具调用
的中间轮），最终答案返回后过程折叠、正文只留定稿。

## 技术方案（内核零改动，跟随上游更新）

Core 的 `AnthropicProvider.achat` 是一次性接口，且其 `EventType` 没有 token 级事件。
按"内核改动要能跟随上游"的约定，**不改 Core 源码**，在 YoAi 包装层实现：

### 1. provider 层（`models/core_anthropic_provider.py`）

- `YOAI_STREAM`（默认 `1`，设 `0` 关闭）控制；
- `_stream_kwargs()`：**复用 Core 公开函数** `split_system /
  to_anthropic_messages / to_anthropic_tools` 组装请求——协议翻译跟随上游，
  不在 YoAi 重造轮子；
- `_achat_stream()`：`async with client.messages.stream(...) as stream: async for event`
  消费 SDK 流式事件，聚合 text/thinking/tool_use input_json + usage 成假响应，
  交 **Core 官方 `parse_response()`** 解析——thinking 回传、工具调用、usage
  全部跟随 Core 语义；
- 文本增量推 `text_outbox`（`round, delta`），每轮 round 递增（含 stall 重试轮）；
- 异常降级、stall 过渡语重试保持原语义；网关不支持 stream 时设 `YOAI_STREAM=0`
  回退一次性路径。

### 2. 事件实时性（`agent.py`）

Core 的 `achat` 是"await 完才返回"，只在事件循环里 drain 会等模型生成完才灌入。
解法：`YoAiAgent.astream` 起后台 poller 每 20ms drain outbox 到 `asyncio.Queue`，
主循环用 `asyncio.wait(FIRST_COMPLETED)` 同时消费 Core 事件与增量队列——
**模型生成期间就实时推出**，不是"返回后一次性补发"。绝不取消 Core 的 `__anext__`
task（会丢事件）。

### 3. UI（`widgets.py` / `main_window.py`）

- `ChatView.append_stream_text(index, round, delta)`：每轮独立缓冲，逐字追加；
  过程块内实时显示（带左边框强调）；
- `delta` 事件由 `_on_event` 接到当前过程块；`collapse_process()` 时
  `stream_visible=False` 隐藏流式区，正文只留一份定稿；
- `_on_done` 用 Core 的 `final_text` 定稿；异常收尾但 final_text 为空时
  以流式缓冲兜底。

## 验证（真跑过）

- provider 离线测试 12 项（假 stream 事件覆盖文本/thinking/tool_use/usage）；
- delta 事件链路 1 项（顺序、round 编号）、UI 流式 1 项（逐字追加 + 折叠）；
- **真实网关冒烟**：单轮流式 `蓝色`（usage 37/34，delta 1 块）；
  两轮工具循环通过——中间轮 `我现在/查询/北京/天气/。` 逐块，
  最终轮 27 个逐字增量，tool_use 聚合正确、无 400；
- 全量 **283 passed**。

## 补充修复：桌面 exe 仍整块出现（同日晚）

第一版只改了 Anthropic 路径，但桌面实际走的是 **SuanliAdapter（讯飞 spark-x2.6，
从 Core .env 读取）→ GatewayModelProvider**（`_build_main_model` 第一优先），
流式 provider 根本没被使用——这是"exe 里还是整块"的真正根因。

修复：

1. **`SuanliAdapter._send_stream()`**：OpenAI 兼容 SSE（`stream:true`）逐行读增量，
   content 进 `text_outbox`、reasoning_content 进 `thinking_outbox`（思考模型增量
   在 reasoning_content），工具调用 arguments 按 index 聚合后交既有提取逻辑；
   `YOAI_STREAM=0` 回退一次性 `post_json`；
2. **`YoAiAgent._outbox_provider()`**：沿 `.base` **和 `.adapter`** 穿透包装链
   ——桌面真实链是 `ExpertModelProvider → GatewayModelProvider → SuanliAdapter`，
   第一版只穿透 `.base` 拿不到 adapter 的增量；
3. 两个既有测试显式 `stream=False` 保持非流式重试语义，新增 SSE 聚合测试
   （content/reasoning/tool_calls/usage）和包装链 drain 测试。

**真实网关验证**：讯飞 spark-x2.6 支持 SSE，单轮返回"蓝色"、`text_outbox` 有增量、
thinking 37 个增量——exe 路径现在也是逐字输出。

## 配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `YOAI_STREAM` | `1` | 设 `0` 关闭流式、回退一次性调用 |
| `YOAI_ANTHROPIC_PROMPT_CACHE` | 关 | 流式路径同样遵守该开关 |

## 边界

- 网关必须支持 Anthropic SSE stream 协议；不支持时用 `YOAI_STREAM=0`；
- thinking 块在流式下按 `thinking_delta` 累积，signature 仍原样保留在 raw blocks；
- QTextBrowser 每次 setHtml 全量重渲染，逐字增量会插 span 标签（视觉无影响，
  测试按内部缓冲断言而非 toHtml 连续字符串）。

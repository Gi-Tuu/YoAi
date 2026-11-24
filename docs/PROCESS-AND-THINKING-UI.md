# 正文过程块：执行过程与 thinking 运行时可见、完成后折叠（2026-11-24）

## 需求与现状

此前执行过程只在右侧 trace 列表里，`model_message` 事件被 UI 直接丢弃，
thinking 更是完全不可见——用户只看到最终答案，像黑盒。

需求：**执行过程和 thinking 在正文里，运行时同步加载（逐条展开显示），
最终结果返回后全部折叠成一行摘要，只保留最终结果，可点击展开回看。**

## 数据来源：thinking 不在 Core 事件流里

核查发现：Core `d4a2204` 把 Anthropic `thinking` / `signature` 块收进
`ModelResponse.raw_content_blocks`，随 assistant 消息存进历史（回传硬要求），
但**只发 `MODEL_MESSAGE` 事件且只带 `text`**，thinking 一行都不发。

按"内核改动要能跟随上游更新"的约定，**不动 Core 源码**，在 YoAi 侧拦截：

1. `CoreAnthropicModelProvider._capture_thinking(response)`：
   从 `raw_content_blocks` 提取 thinking/redacted_thinking 的文本到 `thinking_outbox`
   （signature 无文本不展示；**不动原始块**，回传仍由 Core 负责）；
2. `YoAiAgent.astream` 每个内核事件前 drain outbox，yield `YoAiEvent`
   （`type.value="thinking"`）——worker 只读 `.type.value`/`.data`，无需改 Core enum；
   DONE 后补一次兜底 drain；
3. `ExecutionEvidenceCollector.observe` 按 `EventType` 比较，自定义事件被安全忽略。

## UI：正文过程块

`widgets.py` 的 `ChatView` 新增过程块能力（同一条助手消息内）：

- `begin_process()`：发送时开一条过程块（记 `time.monotonic()` 起跑时刻）；
- `add_process_line(index, text, kind)`：运行时逐条追加 `think/step/result/bad`；
- `collapse_process(index)`：DONE 后折叠，摘要含记录数/步数/耗时；
- 摘要行是 `yoai:process:<index>` 锚点，`anchorClicked` 切换展开/折叠——**可点击回看**；
- 过程行文本也走 markdown 渲染（thinking 里若有 `**` 等不会裸奔）。

## 事件接线（`main_window.py`）

- `_on_send`：先 `begin_process()`；
- `_on_event`：`thinking` → 过程块；`strategy_selected`/`tool_call`/`tool_result`/
  错误类事件在写 trace 的同时 `_add_process()` 到正文（不重复造逻辑）；
- `_on_done`/`_on_error`：把最终结果写进同一条消息正文，然后 `collapse_process()`。

历史加载路径不用过程块（历史是已经完成的消息，直接渲染正文即可）。

## 验证

- `tests/test_thinking_events.py` 4 项：raw_blocks 提取（signature/空白/非 dict 过滤）、
  drain 清空、astream 事件顺序（thinking 先于对应 core 事件）、无 provider 模型行为不变；
- `test_desktop.py` 2 项：过程块展开/折叠/点击摘要、thinking 事件接线 + DONE 折叠 + 表格渲染；
- Markdown 表格语法（`|键|值|`）也已补齐——此前截图里表格原样显示的问题一并修复；
- 全量 **281 passed**。

### 测试组织坑（已记）

QApplication 只能在 `test_desktop.py` 的 module-scope fixture 里创建：
新建独立测试文件自建 QApplication 会与后续 worker 测试的 asyncio 清理竞态，
导致全量跑到 `test_worker_records_expert_id_from_provider` 时 Qt abort（单独跑都过）。
纯 markdown 函数测试留在 `test_markdown_render.py`，Qt 集成测试统一放 `test_desktop.py`。

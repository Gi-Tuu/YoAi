# 模型迁移：主对话切换到 Core 官方 AnthropicProvider

> 2026-11-24。用户拍板（"帮我合并，反正都是我的项目。合并后迁移"）。

## 背景

Anthropic tool_result 400 修复时发现：Core 官方早有 `yai_core.llm.anthropic.AnthropicProvider`
（协议翻译、prompt cache、多模态、thinking 块回传都由 Core 维护）。YoAi 自写的
`DeepSeekAnthropicAdapter` + `GatewayModelProvider` 桥是历史产物，当时不知道 Core 有此实现。
评估结论（对话内，未落文档）：协议翻译已委托 Core、迁移剩余收益有限但方向正确；
主要损失点是 stall 过渡语重试与友好错误降级。用户拍板合并 Core thinking 分支后迁移。

## 做了什么

### 1. Core 侧：thinking 分支合并

- Core 仓库（本机路径不写盘，定位方式见 `yoai.spec` 的 `_find_core_src` 探测顺序）：
  `feat/anthropic-thinking-passthrough`（d4a2204，raw_content_blocks 透传）
  fast-forward 合并进 main，领先 origin 1 提交。
- 验证：Core 相关测试 **63 passed**（tests/test_anthropic_provider.py + test_openai_compat.py）。
- **未 push**（如需推送 origin/main，先按惯例做脱敏检查）。

### 2. YoAi 侧：主对话模型迁移

| 文件 | 改动 |
|---|---|
| `src/yoai/models/stall.py` | **新增**。从 GatewayModelProvider 提取过渡语正则 + nudge 指令（两个 provider 共用） |
| `src/yoai/models/core_anthropic_provider.py` | **新增**。`CoreAnthropicModelProvider`：Core 官方 AnthropicProvider 的生产包装 |
| `src/yoai/models/gateway_provider.py` | stall 正则改为引用共享模块，行为不变 |
| `src/yoai/models/__init__.py` | 导出新 provider 与 `core_anthropic_available()` |
| `src/yoai/desktop/app.py` | `_build_main_model`：Suanli（OpenAI 兼容）→ 旧 GatewayModelProvider 桥；**Anthropic 网关 → CoreAnthropicModelProvider** |
| `yoai.spec` | hiddenimports 增补 anthropic/httpx/anyio 等传输层（SDK 在 Core 内是函数内懒加载，静态分析不可靠） |
| `tests/test_core_anthropic_provider.py` | **新增** 12 项测试（离线假 client） |

### 3. 包装层保留的两件生产资产

1. **异常转友好错误**：Core kernel/loop 对 `achat` 异常 raise 不吞；包装层把 SDK 异常转成
   `[模型网关错误]...` 文本（模型下一轮可自愈或告知用户），语义与旧桥一致。
2. **stall 过渡语重试**：只说"我去查一下"不调工具时追加一次明确指令（2026-11-24 生产修复），
   提取到 `stall.py` 供新旧两个 provider 共用。

### 4. 范围约定

- **peer 聊天不迁**：`ExternalPeer.handle` 依赖同步 `send()` + AdapterResult 吞异常，
  `DeepSeekAnthropicAdapter` 在 registry 保留原样。
- **SuanliAdapter 不动**：OpenAI 兼容网关，不适用 Anthropic 协议。
- prompt_cache 默认**关**（块状 system + cache_control 在 DeepSeek 网关未实测，先保守）；
  环境变量 `YOAI_ANTHROPIC_PROMPT_CACHE=1` 可开启。

## 环境变量（与旧 adapter 完全一致，无配置变化）

```
ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN（或 ANTHROPIC_API_KEY）/ ANTHROPIC_MODEL
ANTHROPIC_MAX_TOKENS（可选，默认 4096，旧 adapter 是 1024）
YOAI_ANTHROPIC_PROMPT_CACHE=1（可选）
```

## 自检（真跑过）

- Core：`pytest tests/test_anthropic_provider.py tests/test_openai_compat.py`
  → **63 passed, 8 warnings in 0.33s**
- YoAi 全量：`pytest tests/` → **240 passed, 50 warnings in 16.40s**（228 旧 + 12 新）
- 真实网关单轮：`CoreAnthropicModelProvider().achat(...)` → 回答"蓝色"，
  usage 37/59，last_status=ok
- 真实网关两轮工具循环：模型发 tool_use → tool 结果回传 → 第二轮正常作答，**无 400**

## thinking 回传说明

Core 合并 d4a2204 后，`parse_response` 把 thinking/redacted_thinking 块收进
`ModelResponse.raw_content_blocks`，下一轮 assistant 消息自动回传（signature 逐字保留）。
迁移后 YoAi 主对话路径**自动获得**该能力，无需配置——台账 #9（转发需求）与 #10（本地绕法）
就此关闭。

## 遗留

- exe 未重打包（模型层改动 + spec 已更新；UI exe 由 Codex 打包时一并带上即可）。
- Core main 领先 origin 1 提交，未 push。

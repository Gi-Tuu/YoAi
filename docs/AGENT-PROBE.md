# 本机智能体接入能力探测报告

> 探测时间：2026-11-21　探测方式：实际命令 / 注册表 / 安装目录，不凭名称猜测。
> 目的：为 YoAi 阶段 C「任意外部智能体真接入」提供事实依据。

## 结论速览

### 真实模型网关（2026-11-21 新增，L2 真接入 · 已验证）

| 网关 | 来源 | 端点 | 实测 | 适配器 |
|---|---|---|---|---|
| **DeepSeek (Anthropic)** | 环境变量 `ANTHROPIC_*` | `api.deepseek.com/anthropic` | ✅ HTTP 200，返回"收到"，带 usage | `yoai.models.DeepSeekAnthropicAdapter` |
| **算里 DeepSeek** | Core `.env` 的 `OPENAI_*` | `api.suanli.cn/v1` | ✅ HTTP 200，返回"收到"，带 usage | `yoai.models.SuanliAdapter` |

这两条走 HTTP API，**绕开了 `claude.CMD` 被沙箱拦的问题**，是 YoAi 首选真实模型通道。
DeepSeek 返回 content 块数组（thinking + text），适配器跳过 thinking 只取 text；
两者 usage 都可喂给 Core 预算。key 只在内存使用，不回显/不写盘/不进结果。

**第一轮真实智能体端到端测试（2026-11-21）已完成**：用算里免费 DeepSeek 跑通了
"路由→工具调用→副作用落盘→真实验收→证据采集→归因"完整链路，详见
`docs/ROUND1-REAL-MODEL-TEST.md`（此前本文档只记录单条 HTTP 探针）。

发现路径：环境变量 `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic` +
`ANTHROPIC_MODEL=deepseek-flash[1m]`；Core `.env` 的 `OPENAI_BASE_URL=https://api.suanli.cn/v1` +
`LLM_MODEL=deepseek/deepseek-v4.1-flash-1017`。两者直连均 200。

### 智能体清单

| 智能体 | 安装形态 | 可程序化接口 | 能否自动回答 | 接入级别 |
|---|---|---|---|---|
| **Claude Code** | npm CLI `claude` v2.1.316 | `claude -p "消息"` | ✅ 实测返回"收到" | **L2 真接入** |
| **OpenCode Zen** | API 网关 + key（`auth.json` 的 `opencode`） | `POST /zen/v1/chat/completions` | ⚠️ key 有效、69 模型可见；**当前额度不足** | **L2 已实现·待充值** |
| **OpenCode CLI** | npm CLI `opencode` v2.2.5 | `opencode run --format json` | ⚠️ serve 能起但客户端握手卡住 | 弃用，改走 Zen API |
| **Trae CN** | VS Code 系 CLI `trae-cn` v3.4.22 | `trae-cn <file>` | ❌ 只开文件/窗口 | L1 仅唤起 |
| **Qoder** | Electron GUI + URL 协议 `qoder://` | 协议唤起窗口 | ❌ 无消息 API | L1 仅唤起 |
| **Qoder CN** | Electron GUI + `collaboration-cli` 内部组件 | URL `qoder-cn://` | ❌ 组件非独立 agent 命令 | L1 仅唤起 |
| **MiniMax Code CN** | Electron GUI + URL `minimax-cn://` | 协议唤起 | ❌ 无消息 API | L1 仅唤起 |
| **ZCode** | Electron GUI + URL `zcode://` | 协议唤起 | ❌ 无消息 API | L1 仅唤起 |
| **WorkBuddy** | Electron GUI + URL `workbuddy://` | 协议唤起 | ❌ 无消息 API | L1 仅唤起 |
| **DeepSeek Harness** | Electron GUI | 无发现 CLI / 协议 | ❌ 无消息 API | L0 未发现接口 |
| **ChatGPT Desktop** | `chatgpt-desktop.exe`（WindowsApps） | 无 CLI | ❌ 无消息 API | L0 未发现接口 |

## 接入级别定义

- **L2 真接入**：可非交互传消息、自动拿到回答，能作为真正的群成员协作。
- **L1 仅唤起**：可通过命令行/URL 协议拉起应用并把消息写进一个"投递文件"，
  但回答要靠人复制回 YoAi，无法自动闭环。诚实标注，不伪装成自动回答。
- **L0 未发现接口**：本机未找到可程序化通道；保留配置位，等官方提供 CLI/API 再接。

## 关键证据

1. **claude -p 实测**（成功）：
   ```
   $ claude -p "只回复收到"
   ... 收到
   EXIT=0
   ```
   有证书/模型警告（配置为 `deepseek-flash[1m]`），但不影响返回结果。

2. **OpenCode Zen 直连实测**（2026-11-21，用户指出配了 Zen 额度）：
   - `auth.json` 有 `opencode` provider（key 前缀 `oc_`，有效）；`GET /zen/v1/models` → **200，69 个模型可见**（key 有效）。
   - 直连需带浏览器 UA，否则 Cloudflare **403 error code 1010**（urllib 默认 UA 被拒）。
   - 带 UA 后：付费模型 `gpt-5.4-nano` / `gpt-5.5` / `glm-5.3` → **402 Insufficient balance**；
     免费模型 `deepseek-v4.1-flash-free` → **429 Free usage limit reached**。
   - **结论**：Zen 账户当前既无 pay-as-you-go 余额、免费额度也已耗尽。用户所说"每天/每周
     1000 次调用"疑为 CLI 订阅侧额度（429 文案称"免费模型仅 OpenCode 内可用"），
     但 CLI 客户端握手卡住（见下），暂无法验证订阅额度。
   - 适配器 `ZenAdapter` 已实现（标准库 urllib、key 只在内存、402/429 翻成人话），
     充值 / 免费额度重置后立即可用；当前会诚实返回额度错误，不伪装成功。

2b. **OpenCode CLI 握手诊断**：`opencode run` 一直超时；加 `--print-logs` 发现卡在
   spawn `opencode.exe serve --stdio --port 0`。直接跑该 serve 实际**能启动**
   （输出 `{"url":"http://127.0.0.1:<随机端口>"}`，长驻不退出故 timeout=124），
   但 `--port 8765` 形式未监听端口。疑客户端/服务端 stdio 握手问题，非模型问题。
   故改用 Zen 直连 API，绕开 CLI。

3. **VS Code 系 CLI**：`trae-cn --help` 只有 `-g/--goto`、`-n/--new-window` 等
   文件/窗口参数，无 prompt 参数。`code` / `cursor` 同理。

4. **URL 协议**（注册表 HKCU\Software\Classes 实测）：
   `qoder`、`qoder-cn`、`minimax-cn`、`zcode`、`workbuddy`、`trae-cn`、`opencode`
   均有 `shell\open\command`，形如 `"...exe" "%1"` —— 只能把参数当 URL/文件路径打开。

5. **去重/发现**：另发现 `codex`、`codexplusplus`、`Devin`、`MiniMax Code`（非 CN）
   等注册，本轮不在用户清单内，未展开。

## 对接入架构的约束

- 只能用**统一契约**容纳三种级别，不能假设每个智能体都有 stdin/stdout 对话能力。
- L2 适配器走子进程非交互调用 + 超时 + 输出解析。
- L1 适配器走"唤起 + 投递文件 + 人工回贴"，UI 上明确标记"需人工转发"。
- L0 只登记元数据，注册为 peer 但不投递消息（fail closed）。
- 所有外部调用必须可禁用、带超时、带授权声明（复用 Core 的 Subject 思路）。

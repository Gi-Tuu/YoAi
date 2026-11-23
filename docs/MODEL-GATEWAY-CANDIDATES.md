# 模型网关候选清单（2026-11-23 搜罗）

> 背景：算里（api.suanli.cn）免费额度于 2026-11-23 到期。搜罗可替代渠道。
> 数据来自公开搜索（ai tu jian 总表 2026-11-23、各平台页面），**额度/端点随时变动，接入前须实测**。

## 一、YoAi 的硬需求（筛选标准）

| 需求 | 说明 |
|---|---|
| OpenAI 兼容 | chat/completions 协议，改 base_url + key + model 即可接入 |
| **tool_calls** | **记忆写入靠模型调 remember_event 工具——不支持函数调用的网关直接出局** |
| 大额度 | 一次全量评测约 11,300 次调用、数百万 token；一次性赠金（10-15元）跑一次就见底 |
| 国内直连 | 无需翻墙 |
| 模型质量 | 需长上下文理解 + 稳定工具调用（当前用 deepseek-v4.1-flash） |

## 二、推荐候选（按能否撑住评测分级）

### A 级 · 每日/每5小时刷新额度，可能撑住评测

| 平台 | 免费额度 | 端点 | 模型 | 注册门槛 | 备注 |
|---|---|---|---|---|---|
| **美团 LongCat** | **每日 5000 万 token** | 需控制台确认 | LongCat 长文本/agent | 需注册 | 额度最大，最值得先试；tool_calls 待实测 |
| **商汤 SenseNova** | 每模型 **1500 次/5小时**、60 RPM | 需控制台确认 | SenseNova 6.8 Flash 等 | 公测免费 | OpenAI 兼容接口（官方称）；工具调用支持待实测 |
| **书生·浦语 InternLM** | 每月 100万输入+300万输出 token | 需控制台确认 | InternLM | 需注册 | 10 RPM，月度额度偏小，适合轻量 |
| **讯飞星火 Spark Lite** | 永久免费 0元/百万 token | 需控制台确认 | Spark Lite | 实名送20万token | **QPS 上限 2**——太慢，不适合评测 |

### B 级 · 官方免费层，额度明确但偏小（适合生产/日常，不够全量评测）

| 平台 | 免费额度 | 端点 | 模型 |
|---|---|---|---|
| **腾讯 EdgeOne Makers** | 每月 50 万 token | `https://ai-gateway.edgeone.link/v1` | DeepSeek v4-pro/v4-flash、Kimi k2.6、混元 hy3、MiniMax |
| **智谱 AI** | GLM-4-Flash 免费 | `https://open.bigmodel.cn/` | GLM-4-Flash |
| **硅基流动** | 注册送 14 元 | `https://cloud.siliconflow.cn/` | DeepSeek/Qwen/GLM 多模型 |
| **阿里云百炼** | 新用户免费 token | `https://dashscope.aliyun.com/` | Qwen 系列 |
| **火山方舟** | 新用户免费 token | 控制台 | 豆包系列 |
| **ModelScope 魔搭** | 每天 2000 次免费推理 | `https://modelscope.cn/my/myaccesstoken` | 50+ 开源模型 |

### C 级 · 聚合网关（额度可能够，但第三方风险自担）

| 平台 | 免费额度 | 端点 | 备注 |
|---|---|---|---|
| AnyAPI | 每日 10 万 token | 聚合 400+ 模型 | OpenAI 兼容，第三方 |
| OpenCode Zen | 免费通用/编程模型 | 聚合 | 含 DeepSeek V4 Flash、Qwen 3.6 Plus 等 |
| OrcaRouter | 多模型 $0/token 自动路由 | 聚合 | DeepSeek V4 Pro/Flash、腾讯 Hy3 |
| apishare.cc | 60 req/min 无日上限 | `https://apishare.cc/v1` | 免费层无日上限（需注册验证真实性） |
| NovAI | 5 个 Flash 模型 10次/天 | `https://aiapi-pro.com/v1` | 免费层 10次/天，不够评测 |
| 幻城网安 | 注册送免费额度 | 公益网关 | GLM/DeepSeek/Qwen/Kimi/Step |

## 三、明确的排除项（别浪费时间）

- **GitHub Models**：2026-07-30 已完全关停
- **Cerebras**：免费改为 $5 试用、需绑卡
- **OpenAI / Anthropic 官方**：无永久免费 API
- **Groq / OpenRouter / NVIDIA NIM**：免费层限流严格（50-1000 次/天），不够评测；且海外端点国内直连不稳
- **一次性赠金类**（Kimi 15元、MiniMax 15元、百川 80元、Together $100 等）：跑一次全量评测就见底

## 四、下一步（接入前必做）

选定候选后，用最小成本验证三件事，再决定是否切换：
1. **端点可达**：`curl` 打 /chat/completions 看 HTTP 200
2. **tool_calls 支持**：发一个带 tools 的请求，看返回是否有 tool_calls 字段——**这是 YoAi 生死线**
3. **额度实测**：看响应头/控制台用量，确认刷新周期与上限

验证通过后，只需改 `.env` 的 `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `LLM_MODEL` 三行，代码零改动。
不建议在评测进行中切换——会在同一批结果里混入不同模型，破坏可比性。

> 注：以上信息为搜罗结果，未经实测；免费政策和端点随时可能调整，以各平台官方页面为准。

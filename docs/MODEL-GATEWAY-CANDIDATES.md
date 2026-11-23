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

### D 级 · packet.ai Token Factory（技术完美，但地区条款受限）

| 项 | 核实结果（2026-11-23） |
|---|---|
| 免费期 | **至 2026-12-15 23:59 UTC（北京 12-16 08:00）**，官方原句 `No money until 15 Dec 2026`，无延期口子 |
| 端点 | `https://api.packet.ai/v1`（OpenAI 兼容，只改 base_url/key/model） |
| 免费模型 | DeepSeek V4.1 Flash (NVFP4)、MiniMax M3.1 Flash、Qwen2.5-1.5B-Instruct |
| tool_calls | **明确支持**（function calling / agentic workflows）✅ |
| 上下文 | DeepSeek/MiniMax 131K（官网写 1M，API 实测 131072，按 131K 估） |
| 注册 | 邮箱/Google + 手机号短信验证一次，无需信用卡；key 以 `hai_tf-` 开头 |
| 模型 ID | 必须连字符版 `nvidia-deepseek-v4-1-flash-nvfp4`（官网斜杠版会 404） |
| 坑 | 默认开思考占 max_tokens（调大）；无公开速率上限（看控制台 Billing→Usage→Limits）；只文本对话无多模态 |
| **⚠️ 地区条款** | **用户协议第 6 节把 China (incl. Hong Kong)、Macau 列受限清单，禁止使用，禁止 VPN 规避**——按条款大陆用户不在服务范围 |
| 到期价 | DeepSeek 输入 $0.23 / 输出 $0.85 每百万 token |

**判断**：技术和额度都极对口（免费一个月、支持工具调用、模型与当前一致），**但地区条款是硬约束**——不建议绕行。若你所在地符合条款则可用；否则按合规渠道选 A/B 级。

### E 级 · Nov Apis（novapis.com，送$100说法待核实）

| 项 | 核实结果（2026-11-23） |
|---|---|
| 端点 | `https://www.novapis.com/v1`（OpenAI 兼容，curl/SDK 示例齐全，支持流式） |
| 支持模型 | 官网列 OpenAI/Claude/Gemini/**DeepSeek**/Grok/Qwen/Mistral/Llama |
| API 能力 | 对话补全、图像生成、文本补全、语音音频、嵌入、批处理（tool_calls 未明确写，需实测） |
| **$100 额度** | **官网查无此条款**——首页/pricing/注册页都只写 Starter $0（"基础请求额度"无数字）、Growth $199/月，且标注"模板展示，以控制台为准" |
| 可能的来源 | 注册页有 **Promo Code 字段**——"送$100"可能是某推广码/邀请码的优惠，非默认政策；网上"注册送100美元"文章说的是另一个平台（需绑卡实名），与本站对不上 |
| 注册 | 邮箱+密码，Promo Code 可选；无需手机/信用卡（页面未见） |
| 性质 | **第三方聚合中转网关**（Sub2API 类），非模型官方；有智能路由、故障转移、用量面板 |

**判断**：技术形态可用（OpenAI 兼容 + DeepSeek），但"送$100"**未经证实**，别按"到手 $100"规划评测预算。
若要试：注册时填 Promo Code，到账后立即在控制台确认余额与有效期；实测 tool_calls 后再决定是否接。
中转网关的隐私/可靠性风险自担（见 C 级说明）。

### 补充：四个指定平台的直达地址与核实状态（2026-11-23）

| 平台 | 注册地址 | API 端点 | 免费额度 | 核实状态 | YoAi 适配 |
|---|---|---|---|---|---|
| **Mistral** | https://console.mistral.ai | `https://api.mistral.ai/v1` | Free层 $10/月（或Experiment层约1B token/月，说法不一） | ✅ OpenAI兼容 Chat Completions、**tool_calls 支持**、免信用卡（需手机号验证）；模型如 `mistral-small-4`、`deepseek-v4-1-flash-1017`（$0.30/$1.20） | **✅ 四者中唯一可接** |
| **LongCat（美团）** | https://longcat.chat/ | 需注册后控制台确认 | 每日 5000 万 token | ⚠️ 官网无公开 API 端点文档，需注册看控制台 | 待核实 |
| **SenseNova（商汤）** | https://www.sensenova.cn/ | 需注册后控制台确认 | 每模型 1500次/5小时、60RPM | ⚠️ 官网首页仅产品介绍，API 端点需注册后看 | 待核实 |
| **Cohere** | https://dashboard.cohere.com/api-keys | `https://api.cohere.com/compatibility/v1` | Trial key 1000次/月、20RPM | ✅ OpenAI兼容端点、**tool_calls 支持**、免信用卡 | ❌ **条款禁用中国大陆/港澳**（同 packet.ai） |

> Mistral 注意：手机号验证必须有；免费层数据在部分地区可能用于改进模型。
> Cohere 注意：OpenAI 兼容端点是 `/compatibility/v1`，原生 API 是 `/v2`（响应结构不同，别混用）。

## 三、明确的排除项（别浪费时间）

- **GitHub Models**：2026-07-30 已完全关停
- **Cohere / packet.ai**：服务条款明确禁用中国大陆（含香港/澳门），禁止 VPN 规避——合规原因不用
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

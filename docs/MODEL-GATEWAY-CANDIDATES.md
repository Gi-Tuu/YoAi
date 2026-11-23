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
| 可能的来源 | 注册页有 **Promo Code 字段**——"送$100"经 Promo Code 领到（用户已领） |
| 注册 | 邮箱+密码，Promo Code 可选；无需手机/信用卡（页面未见） |
| 性质 | **第三方聚合中转网关**（Sub2API 类），非模型官方；有智能路由、故障转移、用量面板 |
| **实测结果（2026-11-23）** | 端点 `https://www.novapis.com/v1/chat/completions` 正确；**模型 ID 带 `openai/` 前缀+后缀**（`openai/gpt-5.6-sol/terra/luna`、`openai/gpt-6-sol/luna`、`openai/gpt-6.1-sol/terra`、`openai/gpt-6.2-astra`）；`/v1/models` 端点 404（网关未实现） |
| 余额问题 | 第一个 key 用真实 ID 返回 HTTP 403 `Insufficient account balance`；换第二个 key 后网关持续 **502 Bad Gateway**（平台侧故障，非 key/余额/模型问题）——**尚未成功发出一次请求** |

### 官方价格（每百万 token，多源交叉验证 2026-11）

| 模型 | 官方输入/输出 | 缓存输入 | 全量评测估算(2.3M/7M token) |
|---|---|---|---|
| gpt-6.2-astra | $8 / $40 | $0.40 | — |
| gpt-6-astra | $10 / $50 | $1.00 | — |
| gpt-6.1-sol | $2 / $10 | $0.10 | $8.28 / $25.20 |
| gpt-6.1-terra | $1 / $5 | $0.05 | $4.14 / $12.60 |
| gpt-6-sol | $2 / $10 | $0.20 | $8.28 / $25.20 |
| **gpt-6-luna** | **$0.10 / $0.50** | $0.01 | **$0.41 / $1.26**（最便宜） |
| gpt-5.6-sol | $4 / $20 | $0.40 | $16.56 / $50.40 |
| gpt-5.6-terra | $2 / $12 | $0.20 | $4.83 / $14.70 |
| gpt-5.6-luna | $0.20 / $1.20 | $0.02 | $0.92 / $2.80 |

> 中转站实付价约为官方 14-17%（aiapiprice.com 抽样）；若网关真"1:1 官方价"，luna 跑全量也仅 $0.4-2.8，$100 绰绰有余。**价格不是瓶颈**。

### ⚠️ tool_calls 兼容性大坑（YoAi 生死线）

- **GPT-6 Astra / 6.1 Sol / 6.1 Terra**：tool calling **必须走 Responses API**，Chat Completions 不支持 → YoAi 直接接会调不动工具
- **GPT-6 Sol / GPT-6 Luna**：Chat Completions 下必须设 `reasoning_effort=none` 才能 function calling
- **GPT-5.6 全系**：Chat Completions 支持 function calling
- 结论：即使网关恢复，也要**逐个实测 tool_calls**，不能只看模型名换上去

**判断**：**当前不可用**（网关 502）。恢复后优先测 `openai/gpt-6-luna`（最便宜）和 `openai/gpt-5.6-luna`（工具兼容最好）的 tool_calls。
即使可用，换模型后结果**无法与 87.2% 对比**（不同 evaluated system），要重跑全量建新基线。

### 🟢 百炼账号免费额度实况（用户从控制台抄录，2026-11-23）

**文本模型（YoAi 可用，全部支持 function-calling、1M 上下文）**：

| 模型 | 剩余免费额度 | 到期(剩余天) | 标准价(元/百万) | 判断 |
|---|---|---|---|---|
| **deepseek-v4.1-flash-1017** | 998.57K | 2027-01-17 (55天) | 免费额度 | ⭐ **评测同款，保 87.2% 可比性；首选** |
| deepseek-v4.1-flash | 999.9K | 2026-12-13 (20天) | 免费额度 | 同系列备用 |
| qwen4-max | 1M | 2027-02-14 (83天) | 10/30 | 最强 qwen，贵 |
| kimi-k3.1-pro | 1M | 2027-02-02 (71天) | 13/68 | 最贵 |
| qwen3.8-flash | 1M | **2026-11-25 (2天)** | 0.8/2.7 | 便宜但即将到期 |
| qwen3.8-max-0902 | 1M | 2026-12-01 (8天) | 12/36 | 快到期 |

其它为视觉/语音模型（qwen-image、paraformer、sambert 等），YoAi 当前用不上。

**额度现实**：每模型仅 **1M token 免费**——一次全量评测要几千万 token，
**免费额度只够小样本验证（约 20-50 题），跑全量必须靠 210 元代金券**（按官方价一次约 ¥150，够跑一次多）。

### 🟢 阿里云百炼 · 全模型清单抓取（2026-11-23）

用 API key 调 `https://dashscope.aliyuncs.com/api/v1/models?page_no=N&page_size=20` 翻页，
抓到**全部 382 个模型**（含价格/特性/上下文），原始数据在 `bench_results/bailian_models.json`。
- **19 个 deepseek 系列**：`deepseek-v4.1-flash-1017`（评测同款）、`deepseek-v4.1-flash`、
  `deepseek-v4-pro`（¥12/¥24）、`vanchin/deepseek-*`、`siliconflow/deepseek-*` 等
- **110 个支持 function-calling**（YoAi 可用）；最便宜：
  `tongyi-xiaomi-analysis-flash`（¥0.2/¥0.4）、`qwen-plus-2025-*`（¥0.8/¥2.0）
- **注意**：账号"有免费额度的 74 个模型"是控制台维度信息，API 不返回，
  需从浏览器控制台看（本次未抓，尊重登录态）

### 🟢 阿里云百炼（2026-11-23 实测通过，可接入）

| 项 | 实测结果 |
|---|---|
| 端点 | `https://dashscope.aliyuncs.com/compatible-mode/v1`（OpenAI 兼容） |
| 可用模型 | 🟢 **`deepseek-v4.1-flash-1017`（评测同款！）**、`deepseek-v4.1-flash`、`qwen-flash`、`qwen-plus`、`qwen-max` 均 HTTP 200；`qwen-turbo` 限流、`qwen3-*` 无权限、`deepseek-v4-pro` 免费额度已耗尽 |
| **tool_calls** | **✅ 完美支持**——强制触发下 finish_reason=`tool_calls`，返回标准 `remember_event` 调用；deepseek-v4.1-flash-1017 和 qwen-flash/plus 都验证过 |
| 响应 | 0.5-0.8s（很快） |
| 注意 | 模型 ID 用**小数点** `deepseek-v4.1-flash-1017`（连字符版 `deepseek-v4-1-flash-1017` 不存在）；`/models` 端点不可用（404/空）；默认开思考（reasoning_content 占 max_tokens，调大到 1024+） |
| 注册 | 用户已领到 key（sk-ws- 开头） |

**判断**：**这是今天所有候选里唯一能保住 87.2% 可比性的替代网关**——
`deepseek-v4.1-flash-1017` 正是评测用的同款模型，换上去后分数口径不变。
百炼是官方平台、国内直连、响应快、有免费额度。**强烈建议作为算里到期后的评测/生产首选迁移目标。**
唯一注意：debug 时要确认路由到的是 deepseek 而非 qwen（模型 ID 写死）。

### ✅ 迁移验证（2026-11-23，同题 A/B）

- 算里 key 已失效（401 "当前 API Key 不存在"）——免费额度确实到期，迁移是必须的
- 用环境变量覆盖把评测/评分切到百炼（`YOAI_BASE_URL` / `YOAI_API_KEY` / `YOAI_MODEL` /
  `YOAI_JUDGE_MODEL`，不动桌面默认配置），跑 30 题
- **结果：百炼 23/30 = 76.7%，算里同题 23/30 = 76.7%——总分完全一致**
- 4 题翻转（2 正 2 反）属模型随机抖动，与同配置两次运行翻转 16/100 的量级一致
- **结论：同模型（ds-v4.1-flash-1017）不同网关，分数可比，迁移安全**
- 产物：`bench_results/lme-bailian-30/`；代码提交 `1c2f70f`；188 passed

> 复现：评测和评分时都设 `YOAI_*` 四个环境变量（key 从本地文件读，不进 git）。
> judge 模型 ID 用百炼格式 `deepseek-v4.1-flash-1017`（不带 `deepseek/` 前缀）。

### 🏆 全量 500 题迁移验证（2026-11-23 晚，最终）

30 题验证后又在百炼上跑完整 500 题（`bench_results/lme-bailian-500/`）：

| 网关 | 总分 | 说明 |
|---|---|---|
| 算里（旧，key已失效） | 436/500 = 87.2% | 不可复现 |
| **百炼（新，当前可用）** | **436/500 = 87.2%** | **可复现基线** |

- 同题翻转 **68 题，但恰好 34 对 34 错完全对称**；McNemar 卡方 0.015（p≈1）→ 统计上零差异
- 分题型有波动（temporal 85.7→92.5%、multi 79.0→74.4%），属模型随机性重新分配，总分不变
- **权威成绩 87.2% 现在是"当前网关可复现"的** —— 解决了算里 key 失效导致不可复现的风险

**usage 首次实测（降本结论）**：
- 总 token **1.13 亿**（31977 次调用），其中 prompt 9594 万、completion 1704 万
- **缓存命中 5963 万 = 62.2%** —— 缓存不是金矿，已经用掉大半
- 成本：空闲时段（晚间/周末）约 **¥106**，高峰约 ¥211；缓存省了 36%
- **最大降本杠杆 = 错峰跑（晚间半价），不用改代码**

> 之前"一次评测几十块"的估算是批量口径低估；实测 ¥106（空闲）~¥211（高峰）。

### 补充：四个指定平台的直达地址与核实状态（2026-11-23）

| 平台 | 注册地址 | API 端点 | 免费额度 | 核实状态 | YoAi 适配 |
|---|---|---|---|---|---|
| **Mistral** | https://console.mistral.ai | `https://api.mistral.ai/v1` | Free层 $10/月（或Experiment层约1B token/月，说法不一） | ✅ OpenAI兼容 Chat Completions、**tool_calls 支持**、免信用卡（需手机号验证）；模型如 `mistral-small-4`、`deepseek-v4-1-flash-1017`（$0.30/$1.20） | **✅ 四者中唯一可接** |
| **LongCat（美团）** | https://longcat.chat/ | 需注册后控制台确认 | 每日 5000 万 token | ⚠️ 官网无公开 API 端点文档，需注册看控制台 | 待核实 |
| **SenseNova（商汤）** | https://www.sensenova.cn/ | 需注册后控制台确认 | 每模型 1500次/5小时、60RPM | ⚠️ 官网首页仅产品介绍，API 端点需注册后看 | 待核实 |
| **Cohere** | https://dashboard.cohere.com/api-keys | `https://api.cohere.com/compatibility/v1` | Trial key 1000次/月、20RPM | ✅ **免费试用属实**（用户确认+多源核实）、OpenAI兼容端点、**tool_calls 支持**、免信用卡免手机 | ❌ **条款禁用中国大陆/港澳**（同 packet.ai）——免费是真的但不能合规使用 |

> Mistral 注意：手机号验证必须有；免费层数据在部分地区可能用于改进模型。
> Cohere 注意：OpenAI 兼容端点是 `/compatibility/v1`，原生 API 是 `/v2`（响应结构不同，别混用）。

### 💡 决策依据：官方 DeepSeek 直连其实最划算（2026-11-23 核实）

官方价格页 https://api-docs.deepseek.com/zh-cn/quick_start/pricing（人民币/百万token）：

| 模型 | 输入(缓存命中) | 输入(未命中) | 输出 | 并发 |
|---|---|---|---|---|
| **deepseek-flash**（=V4.1-Flash-1017，当前评测模型） | 空闲 ¥0.02 / 高峰 ¥0.04 | 空闲 ¥1 / 高峰 ¥2 | 空闲 ¥4 / 高峰 ¥8 | 250 |
| deepseek-v4-pro | 空闲 ¥0.15 / 高峰 ¥0.30 | 空闲 ¥4.5 / 高峰 ¥9 | 空闲 ¥13.5 / 高峰 ¥27 | 500 |

- 高峰=北京时间工作日 9-12点、14-18点；其余含周末全天**半价（空闲）**
- **一次全量评测成本（实测修正）**：早先用批量口径 token 量估的 ¥3.7–22.4 **严重低估**——
  单轮递增是 10800+ 次独立调用，每次都带完整 system prompt + 工具定义，token 量比批量高一个量级。
  2026-11-23 全量 500 题实跑，算里网关按官方价**换算约 ¥150**（用户确认，平台正规）。
  即官方 ds 跑一次全量实际约 ¥150，仍够跑很多次，但别再按几十块估。
- 官方直连 `https://api.deepseek.com`，base_url 换成它、key 用官方的即可，**零代码改动、成绩与 87.2% 完全可比**
- 换算：flash 输出 ¥4/百万≈$0.56，与最便宜的 GPT-6 Luna($0.50) 同量级，但性能强得多；比中端 GPT($10 输出)便宜十几倍

**结论**：中转站"免费额度"看着香，但官方 ds 一次全量才几十块、稳定无地区条款、模型同系列可比。
若评测/开发要长期做，**直接充官方 DeepSeek 是最省心的选择**——免费搜罗可作为应急备选，不必投入过多精力。

### 用户收集的资源清单（2026-11-23 截图，17 条）

按今天验证过的事实分类：

**已验证**：
- 阿里百炼 → 上文，实测通过，当前评测网关
- Nov Apis（100刀）→ 上文，403余额不足/502，不可用
- Cohere（每月1千次）→ 免费属实但地区禁用中国大陆/港澳
- OpenRouter（每天50次）→ 限流严、海外端点，不够评测

**值得验证（额度大）**：
- **RusherAI｜每周5千万词元** — 额度最大（百炼免费的50倍），若支持 ds 同款+tool_calls 则最有价值，待探测
- 亚马逊｜200刀 — 需确认是 AWS 试用还是 Bedrock，额度大但信息不明
- GroqCloud｜每天20万词元 — 海外端点、模型固定，未验证
- APIfreeLLM｜每天1万次调用 — 次数多但看额度/模型
- TokEasy｜70万 — 小，够小样本

**对 YoAi 意义有限**：Agnes AI、NVIDIA NIM、讯飞星辰MaaS、CanTrustAI、
Tavily（搜索非LLM）、AI Gateway($5/月)、Inferbase(5千次/月)、BazaarLink(60次/天)。

> 下一步：全量评测跑完后，优先探测 RusherAI（需 key+端点）。

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

## 五、⚠️ 换网关 = 换模型 = 成绩不可比（最重要）

当前权威成绩 **87.2%** 是在 `deepseek/deepseek-v4.1-flash-1017` 上跑出来的。
任何新网关若提供的是**不同模型**（如 novapis 只有 GPT-5.6/6.x），切换后：

- 记忆抽取行为变（tool_calls 格式、工具选择倾向、自记稳定性都不同）
- 答案质量变 → **新分数不能和 87.2% 比**，等于换了一个 evaluated system

**正确做法**：
1. 优先找**同系列 deepseek** 的网关（Mistral 平台的 `deepseek-v4-1-flash-1017` $0.30/$1.20 就是同系列）
2. 若不得不用不同模型，必须**重新跑全量 500 题**建立新基线，并标注"不同模型口径"
3. 绝不在同一批评测里混用两个网关/模型（破坏可比性）

> 注：以上信息为搜罗结果，部分经 API 实测（novapis），部分待注册后验证；免费政策和端点随时可能调整，以各平台官方页面为准。

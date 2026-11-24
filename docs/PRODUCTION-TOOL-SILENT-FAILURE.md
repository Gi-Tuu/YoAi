# 生产静默失败根因：记忆意图被路由误判（2026-11-24）

## 现象（真实生产观察）

用户反馈：
1. 工具调用能发出，响应不落地——DSML 块被解析被发出，但没有任何结果块回到上下文
2. 失败是静默的——没有 error、没有 timeout、没有空列表，什么都没有
3. 纯对话不受影响，一碰工具后面那段就丢
4. 最致命：**智能体无法区分"库里没有记忆"和"记忆查询根本没成功"**——
   用户问"我上次说过的偏好是什么"，agent 会一本正经回答"你没提过"

## 复现与根因链

脚本直连复现（bench/probe_fc_choice.py）：

```
[记住我偏好深色主题] 策略=['direct'] 工具=[] 错误=1
  ERR: 模型返回了未识别的工具调用文本，本次没有执行任何工具
  模型正文: <tool_call>remember_fact<arg_key>fact</arg_key>...
```

根因链（逐层）：

1. Core `AdaptiveRouter` 的关键词表 `_ACTION_HINTS` 里有"记录"但**没有"记住"**
   → "记住我偏好X"被判 `Strategy.DIRECT`（无需工具的直接问答）
2. DIRECT 模式 `use_tools=False`，**不向模型注入任何工具 JSON Schema**
3. 但 system prompt 里仍注入了工具能力目录（文本）——模型看到目录，
   按文本协议把工具调用写成正文 DSML（`<tool_call>...</tool_call>`）
4. Core 的 `react.py:_looks_like_raw_tool_call` 防线**正确地拒绝**执行 DSML
   （协议与权限都不可信，安全设计，不能开后门）
5. 结果：记忆没写入 + 一条 error 事件；桌面 UI 没把 error 显示出来 → 用户视角"静默失败"

**关键澄清**：这不是讯飞模型的问题，也不是 Core 的 bug——是 Core 规则表的覆盖盲区
（"记住"没进行动信号词表），加上 DIRECT 模式仍注入目录文本的设计组合。

## 为什么昨天的"tool_calls 完美适配"结论错了

昨天用 `tool_choice="required"` + 简单 system prompt + 1 个工具直接调 API——
那是**最容易成功的条件**。生产实际是当时 12 个工具 + 路由决定不给 schema + 多轮上下文，
模型走的是完全不同的协议（DSML）。测了理想条件就下结论，误导了判断。

> 工具数已随 ① 实操工具增加到 18 个（12 记忆/目标 + 4 文件 + 2 联网）。

## 修复（方案 B：Core SPI 扩展，不改内核）

按项目约定"内核可以改，但要能适应 Core 自身更新"——优先用 Core 已提供的扩展点：

- 新增 `src/yoai/routing.py`：`MemoryIntentSelector`
  - 实现 Core 的 `RouteSelector` Protocol（`suggest` / `record`）
  - 纯本地正则匹配，零网络/零模型调用，可放路由热路径
  - 记忆**写入**意图（记住/记一下/我叫/我喜欢/我的X是…）→ 建议 REACT
  - 查询意图（列出/有哪些/是什么…）**排除**，交回 Core 规则（Core 已能识别）
  - 空任务/无工具是 Core 硬规则区，不越过
- `YoAiAgent(..., memory_intent_routing=True)` 默认通过 `AgentCore(learning=...)` 注入
  - Core 升级天然兼容（用的是公开 SPI，不改内核文件）
  - 传 `False` 恢复纯 Core 行为

**没有做的事**：没有改 Core 的 DSML 安全防线，没有改 `_ACTION_HINTS` 词表——
前者是安全机制不能开后门，后者改内核跟不上 Core 更新。

## 验证

- 单测 `tests/test_routing.py`：写入意图→REACT、查询意图不表态、硬规则区不越过、record 空实现
- 真实生产路径（讯飞 spark-x2.6）：
  - "记住我偏好深色主题" → 策略 `react`、调用 `remember_fact`、**零错误**、回答"已记住"
  - "列出我记住的所有事情" → 策略 `react`、调用 `list_facts`、零错误
  - "我叫什么名字？" → 正确回答"没记住名字，但你之前说过偏好深色主题"
- 关闭开关 `memory_intent_routing=False` → 策略回到 `direct`（旧行为可控恢复）
- **201 passed**

提交 `175d1b1`。

## 路由方案的演进：从打地鼠到根治（2026-11-24，重要教训）

**第一版（已废弃）**：在 Core 词表盲区上补正则——漏了"记住"补"记住"，
漏了"写文件"补"写文件"（`MemoryIntentSelector` + `_WRITE_INTENT` / `_FILE_OP` 正则）。

**你指出的问题**："规则表怎么能覆盖全部呢？"——完全正确。词表永远是穷举，
下一个没收录的中文说法照样静默失败。我在错误的方向上做了两轮补丁。

**根治（`a35e7dc`，当前实现）**：
- 真正根因不是词表不全，是 **DIRECT 的设计矛盾**：不给工具 schema，却在 system prompt
  里塞了工具目录文本 → 模型看到目录没 schema → 吐 DSML → Core 安全防线拒绝 → 静默失败
- 方案：`YoAiRouter` 继承 Core 公开类 `AdaptiveRouter`（不改内核、升级兼容），
  **有工具就一律 REACT、注入完整 schema**，让模型自己决定调不调；
  无工具/模糊短句交回 Core 硬规则（CLARIFY/DIRECT 保留）
- 成本可接受：18 个工具 schema 实测仅 **4.2KB**；模型不调工具时 REACT 也就一轮，
  DIRECT 省的那点开销远不值整个静默失败问题类
- 所有词表补丁（`_ACTION_HINTS` 之外的正则）**全部删除**
- 验证：'瞅一眼'、'捣鼓个文件'、'刻到文件里'等**词表外说法**全部走 react、零错误；207 passed

**教训**：遇到"规则覆盖不全"的问题，先问"这个规则层该不该存在"，
而不是继续往里加词。DIRECT 模式在有工具的宿主里本身就是个矛盾设计。

## 后续两项已实施（2026-11-24，用户要求先 ② 后 ①）

### ② error 事件在桌面 UI 不可见 → 已修（`5d4616b`）

- `_on_event` 的 error / permission_denied / budget_exceeded 现在**在主对话区显示** `⚠️ 具体原因`
  （此前只躺在 trace 的 tooltip 里）
- 新增 `_task_had_error` 标志：Core 可能"报错后仍发 done"，此时状态标**部分失败**而非"已完成"，
  避免 agent 把"查询失败"答成"你没提过"
- 新增 2 个 UI 测试；全量 203 passed

### ① 实操工具缺失 → 已修（`d125715`）

- 新增 `src/yoai/tools_builtin.py`：用 **Core 现成电池** `filesystem_capabilities` +
  `filesystem_gate` + `build_spec`（公开 API 注入，**内核零改动、升级兼容**）：
  - `file_list` / `file_read` / `file_create` / `file_patch`
  - 根目录：项目内 workspace/；**读全根目录、写限白名单子目录**（默认 notes/）
  - 写工具挂 gate：越界写被拒（实测 "outside.txt 不在允许的写作用域 ['notes/'] 内"）
  - 大小上限 / 符号链接防护用 Core 保守默认值
- 联网：`web_search`（freeserp.ai 无 key）+ `web_fetch`（仅 https、超时、长度限制）
- 路由由后面的**工具优先路由**根治（词表补丁已废弃，见文首演进章节）
- 桌面端默认开（`YOAI_BUILTIN_TOOLS=0` 可关），CLI 默认关
- **端到端验证**：真实模型（讯飞）写文件→读回，零错误、文件真实落盘

> 安全边界按你的选择：workspace/ 为根、写限白名单子目录、联网一起加。
> 工具能力是"内部大胆、外部谨慎"——写有 gate、联网只读、失败如实返回错误文本。

## 交付产物坑：exe 没更新 + session 路径遗漏（2026-11-24 末）

上面所有"验证通过"当时都是**跑源码**（`PYTHONPATH` 指向 `src/`），而用户实际用的是
`dist/YoAi.exe`——它的时间是 01:57，比当天 12:31–13:07 的源码修复早 11 小时，
**用户用的打包快照里一个修复都没有**。用户一句"是不是 exe 没更新"点破。

重新打包（`yoai.spec` 加 `yoai.routing` / `yoai.tools_builtin` 到 hiddenimports）后，
跑 exe 自检（`YoAi.exe --self-check`）又发现**仍只有 12 个工具**——更深的 bug：

- 桌面真实走 `SessionManager.current_agent()` 建 agent，用默认参数 `builtin_tools=False`
- 之前只在 `main_window` 的**直接构造**处开了开关，对 session 路径无效
- 修复（`e0a279c`）：`SessionManager` 加 `agent_kwargs` 透传；app.py 两个 SessionManager
  构造点（主程序 + 自检）都显式传 `_agent_kwargs`（默认开、`workspace_root` 指向
  数据目录下 workspace/、`YOAI_BUILTIN_TOOLS=0` 可关）

**最终验证**：13:25 重新打包的 exe，`--self-check` 输出 **18 个工具**
（`file_list/read/create/patch` + `web_search/fetch` 全在）；源码 212 passed。

**教训（已写入项目日志）**：改完源码必须验证**用户实际运行的产物**（exe），
不能只跑源码测试。exe 自检 `--self-check` 是验证打包产物的关键手段。

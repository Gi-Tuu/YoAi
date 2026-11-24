# YoAi 自检反馈落地：五项工具能力（2026-11-24）

> 来源：YoAi 桌面实例对自己的能力边界做了自检并给出 6 点反馈（18:24 对话记录）。
> 用户拍板"全部落地"。全部在 YoAi 侧实现，Core 内核零改动。

## 逐项落地

| # | YoAi 的诉求 | 落地方式 | 文件 |
|---|---|---|---|
| 5 | 缺时间源，读不到系统时钟 | `now()` 工具：本地 ISO 8601 带时区时间 | `capabilities.py` |
| 6 | 只有写没有删，重复键堆积 | KV：`forget_fact(key)`（PersonalContext 本就有 forget，只是没暴露）；事件：TemporalMemory 新增 `forget(what, tag)` 精确匹配删除 + `recent_events(n)` 供删除前核对原文 | `capabilities.py`、`temporal_memory.py` |
| 4 | 文件工具读不了项目源码（PathEscapeError 拒绝盘符路径） | 只读挂载扩展根：`file_ro_list` / `file_ro_read`，路径 resolve 后必须落在白名单根内；写类操作不存在；相对路径按白名单根逐个解析；默认不挂载，`YOAI_READONLY_ROOTS`（os.pathsep 分隔）开启 | `tools_builtin.py`、`agent.py`、`desktop/app.py` |
| 2 | 想要 `list_tools` 自省能力边界 | 常驻 meta 工具：运行时如实列出全部工具名+描述（闭包读 `_all_tool_specs`，含它自己） | `agent.py` |
| 3 | `request_capability` 不在表里（鸡生蛋问题） | Core 本就有实现（`yai_core.tools.meta.build_request_capability_tool` + kernel 拦截），只是没注册——现已常驻注册，handler 由 loop 接管 | `agent.py` |
| 1 | 会话开始固定工具表，新工具要新会话可见 | 属 Core 设计（工具表构造时绑定），维持不变；本批工具全部构造期注册，新会话即生效 | — |

## 设计决策

- **删除类工具（forget_fact / forget_event）不进 auto 白名单**：auto 权限档下弹窗确认，
  与文件写同一待遇（桌面 `app.py` 的 `readonly_and_internal` 白名单只加只读项：
  `now` / `recent_events` / `list_tools` / `file_ro_list` / `file_ro_read`）。
- **删除语义用精确匹配**：`forget` 按 what 原文全字匹配，不子串匹配（防误删）；
  模型须先用 `recent_events` / `facts_by_tag` / `list_facts` 拿准确原文，找不到时如实返回 0 并提示先查。
- **只读挂载默认关**：`YOAI_READONLY_ROOTS` 显式开启；根不存在时该根被跳过；
  符号链接逃逸被 resolve 后的归属检查排除（跟随出根即拒绝）。
- **错误文本伪装观察（第 7 点）记录为设计备忘，暂不改**：机制上工具结果由宿主构造、
  模型无法伪造 tool 通道；`[模型网关错误] ...` 是 YoAi 桥接层的错误文本格式，
  出现在对话中属历史数据回灌/模型模仿，非机制漏洞。将来若要根治，方向是系统回执
  结构化（Core ModelResponse 层面），届时立 Core 侧需求。

## 自检（真跑过）

- 新增 `tests/test_meta_tools.py` 9 项：now 带时区且贴近真实时钟、重复键两条同删、
  删除须原文精确匹配、KV 删除、list_tools/request_capability 注册且自列、
  只读挂载白名单内外行为、agent 接线。
- 全量：`pytest tests/` → **249 passed, 55 warnings**（240 + 9）。
- exe 重新打包 + 自检通过（工具数 24：18 + file_ro_list + file_ro_read + meta 计入）。

## 使用方式

- 只读挂载（调试宿主项目）：
  ```
  set YOAI_READONLY_ROOTS=<宿主项目根>      ; 多个根用分号分隔
  ```
- 新工具在**新会话**生效（工具表会话开始时绑定，Core 设计）。

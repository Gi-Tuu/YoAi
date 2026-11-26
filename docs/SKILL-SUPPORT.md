# Skill 技能包基础层（2026-11-26）

> YoAi 侧扩展，Core 零改动。第一阶段目标：**可发现 + 按需加载 + 可管理**。

## 定义

一个 Skill 是一段配置化的「能力提示词 + 建议工具」：

```json
{
  "skills": [
    {
      "name": "research",
      "description": "结构化调研流程",
      "prompt": "先列出主题，再逐条汇总证据，最后给出不确定性说明。",
      "tools": ["web_search", "web_fetch"],
      "enabled": true
    }
  ]
}
```

配置文件：`<data_dir>/skills/skills.json`。桌面生产通常是：

```
<exe所在目录>/output/skills/skills.json
```

## 工具

自动注册四个元工具：

- `skill_list()`：列出技能、脚本包、资源包；
- `skill_load(name)`：返回 prompt、建议工具、脚本/资源清单；`enforce_tools=true` 时叠加工具白名单；
- `skill_run(name, script, args)`：运行声明的脚本包；
- `skill_resource_read(name, path)`：读取声明的资源包文本文件。

模型按需调用 `skill_load` 后才看到技能细节，避免所有技能提示词常驻上下文。

## 脚本包与资源包

目录约定（相对 `<data_dir>/skills/<name>/`）：

```json
{
  "skills": [{
    "name": "demo",
    "prompt": "演示技能",
    "tools": ["web_search"],
    "enforce_tools": true,
    "scripts": [{"name": "upper", "path": "scripts/upper.py", "timeout": 15}],
    "resources": ["templates/report.md"]
  }]
}
```

- 脚本：`sys.executable <script.py>`，stdin 传 JSON args，stdout 解析 JSON 或按文本返回；
  不经 shell，白名单环境变量，超时终止，cwd 限定技能目录。
- 资源：只能是 manifest 中声明的路径，禁止 `..` 逃逸，文本上限 20 万字符。

## 强制工具白名单

`enforce_tools=true` 时，调用 `skill_load` 会在当前 agent 叠加白名单：
技能声明工具 + `skill_list/load/run/resource_read/list_tools`；
再与专家白名单取交集，下一轮 `astream` 生效。技能加载工具始终保留，避免把自己锁死。

## 安全边界

- 技能只提供提示词与建议工具，**不自动授权工具**；
- 工具调用仍走当前权限档位（full / smart / manual）与审批；
- 配置只在本地，不上传；页面不自动回显配置到日志；
- 坏配置不会让主对话失败，读取失败时按空技能集处理。

## 桌面管理页

左侧「技能」页：
- 查看技能名称、描述、prompt、建议工具；
- 查看 `skill_list` / `skill_load` / `skill_run` / `skill_resource_read` 四个元工具；
- 直接编辑并保存 `skills.json`，保存后立即重载。

协议：`skill.status` / `skill.config_get` / `skill.config_set` / `skill.reload`。

## 明确未做

- Skill 依赖版本管理（requirements / lockfile）；
- Skill 市场或远程安装；
- Skill 自动纳入 RSI 候选（后续可做）。

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

自动注册两个元工具：

- `skill_list()`：列出可用技能名称与描述；
- `skill_load(name)`：返回该技能的 prompt 与建议工具列表。

模型按需调用 `skill_load` 后才看到技能细节，避免所有技能提示词常驻上下文。

## 安全边界

- 技能只提供提示词与建议工具，**不自动授权工具**；
- 工具调用仍走当前权限档位（full / smart / manual）与审批；
- 配置只在本地，不上传；页面不自动回显配置到日志；
- 坏配置不会让主对话失败，读取失败时按空技能集处理。

## 桌面管理页

左侧「技能」页：
- 查看技能名称、描述、prompt、建议工具；
- 查看 `skill_list` / `skill_load` 两个元工具；
- 直接编辑并保存 `skills.json`，保存后立即重载。

协议：`skill.status` / `skill.config_get` / `skill.config_set` / `skill.reload`。

## 明确未做

- Skill 内的脚本包 / 资源文件 / 版本依赖；
- Skill 自动绑定工具白名单并强制过滤；
- Skill 市场或远程安装；
- Skill 自动纳入 RSI 候选（后续可做）。

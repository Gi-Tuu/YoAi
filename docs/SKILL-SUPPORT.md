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

## 依赖版本管理

manifest 可声明：

```json
{
  "skills": [{
    "name": "demo",
    "requirements": ["requests>=2.31,<3"],
    "requirements_file": ""
  }]
}
```

- `requirements`：内联依赖列表；留空时读取 bundle 内 `requirements.txt`。
- `generate requirements`：把内联依赖写入 `<data_dir>/skills/<name>/requirements.txt`。
- `generate lockfile`：调用 `uv pip compile --python <当前 Python> requirements.txt -o requirements.lock.txt`，
  解析传递依赖并锁定版本；不会自动安装包。
- 需要本机已安装 `uv` 并在 PATH 中；找不到时明确报错，不自动下载。
- 技能页显示 requirements/lock 是否已生成，并提供两个生成按钮。

协议：`skill.requirements_generate` / `skill.lock_generate`。

## 本地技能市场

市场是本地目录式，不做远程下载：

- `market.json`：登记的技能包目录；
- `market/<name>/`：发布后的技能包；
- 登记本地包：读取 `<包目录>/skill.json`，校验 name；
- 安装：复制包到 `<data_dir>/skills/<name>/`，确保 `requirements.txt` 存在，
  随包带入 `requirements.lock.txt`，更新 `skills.json` 并刷新技能；
- 发布：把已安装技能连同 `skill.json`、`requirements.txt`、`requirements.lock.txt`（如有）
  复制到市场目录；
- 移出市场：只删除市场登记，不动已安装技能文件。

协议：`skill.market_list` / `market_add` / `market_install` / `market_publish` / `market_remove`。
桌面「技能」页提供登记本地包、安装、发布到市场、移出市场按钮。

## 明确未做

- 远程市场与自动下载；
- Skill 自动纳入 RSI 候选（后续可做）。

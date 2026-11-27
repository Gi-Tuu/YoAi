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

## 技能市场（本地 + 远程 catalog）

本地市场是目录式；远程市场只拉取 http(s) catalog 与 zip 包，不自动安装依赖：

- `market.json`：登记的技能包目录；
- `market/<name>/`：发布后的技能包；
- 登记本地包：读取 `<包目录>/skill.json`，校验 name；
- 安装：复制包到 `<data_dir>/skills/<name>/`，确保 `requirements.txt` 存在，
  随包带入 `requirements.lock.txt`，更新 `skills.json` 并刷新技能；
- 发布：把已安装技能连同 `skill.json`、`requirements.txt`、`requirements.lock.txt`（如有）
  复制到市场目录；
- 移出市场：只删除市场登记，不动已安装技能文件。

远程源：`market_sources.json` 保存 catalog URL；catalog 条目格式：

```json
{"skills":[{"name":"demo","version":"1.0","description":"…",
 "url":"/demo.zip","sha256":"<sha256>",
 "signature":"<base64 ed25519>","public_key":"-----BEGIN PUBLIC KEY-----...",
 "requirements":["requests>=2.31"],"lockfile_url":"/demo.lock.txt"}]}
```

- 相对 URL 按 catalog 地址解析；
- zip 包安全解压：拒绝绝对路径与 `..`；
- `sha256` 存在时强制校验，不匹配直接拒绝；
- `signature` + `public_key`（或 `public_key_url`）存在时，用 Ed25519 校验原始 zip 字节，
  校验在解压前完成，失败直接拒绝；
- requirements/lockfile 可由 catalog 提供，随包写入安装目录；
- 安装后自动在技能自己的 `.venv` 中按 lockfile（无则 requirements）安装依赖，
  日志写 `deps_install.log`；失败不破坏技能安装；
- `skill_run` 优先使用技能 `.venv` 的 Python；
- 技能安装后自动在 EvolutionArchive 创建 `candidate` 节点（tools/prompt/tags 来自 manifest），
  写 `rsi_skill_candidate` 报告，不进路由、不晋升。

协议：`skill.market_list` / `market_add` / `market_add_remote` / `market_refresh_remote` /
`market_install` / `market_publish` / `market_remove`。
桌面「技能」页提供远程源地址、刷新远程、登记本地包、安装、发布、移出按钮。

## R5 远端证书透明度（CT）

远程 catalog 可为条目追加：

```json
{
  "ct_url": "https://ct.example.org/log",
  "ct_public_key": "-----BEGIN PUBLIC KEY-----..."
}
```

- 远端公钥必须来自 catalog；**绝不采信回执自带的 public_key**，
  若回执自带公钥则必须与 catalog 公钥一致，否则拒绝；
- 回执包含 `sha256` / `name` / `root` / `proof` / `signature`；
- leaf = SHA256(`0x00 || canonical(条目)`)，node = SHA256(`0x01 || left || right`)；
- Merkle inclusion proof 校验条目确实进入 root；Ed25519 签名覆盖
  "条目 + root + proof"，防止证明被掉包；
- 安装远程包时若提供 `ct_url`，会先拉取回执并校验，失败直接拒绝安装；
  只给 `ct_url` 不给 `ct_public_key` 也拒绝；
- `校验远端 CT` 可随时复验；`锚定到远端 CT` 是显式 POST `/anchor`，
  回执验签通过后才写入本地透明日志；
- 本地透明日志仍是 append-only hash chain，`status.transparency` 给出
  条目数与链是否完整。

协议：`skill.ct_verify` / `skill.ct_anchor` / `skill.ct.result`。
桌面「技能」页展示包 sha256、CT 回执指纹、透明日志状态与校验/锚定按钮。

## 明确未做

- 自动下载未登记 URL；
- 公网 CT 服务的自建部署与跨客户端 gossip 审计（2026-11-27 你拍板暂时不做；当前只校验外部 CT 回执 + 显式锚定，不自动提交）；

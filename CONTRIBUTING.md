# 贡献指南（Contributing）

感谢你对 YoAi 的兴趣。在提交贡献前，请阅读以下内容。

## 1. 许可与版权

- 本项目当前采用 **PolyForm Noncommercial License 1.0.0**（见 `LICENSE`）：
  允许个人研究、学习、实验等非商业用途，禁止商业使用。
- **所有贡献必须同意 `CLA.md`（贡献者许可协议）**：你提交的代码版权将转让给项目权利人，
  使项目方能集中决定协议演进（包括未来可能放开商用）。这是项目控制权的基础。

## 2. 如何表示同意 CLA

提交 Pull Request 时，在 PR 描述中明确写一句：

```
我已阅读并同意 CLA.md，确认本次贡献的版权按 CLA 条款转让给项目权利人。
```

或在贡献文件头部加一行：

```
// SPDX-Contributor: 我已阅读并同意 CLA.md（<your-email>, <date>）
```

## 3. 贡献流程

1. Fork / 分支：`git checkout -b feature/your-change`
2. 改动前先跑一次基线测试，确认起点是绿的：
   ```bash
   QT_QPA_PLATFORM=offscreen PYTHONPATH="src;E:/Competition/YAI Agent Core/src" python -m pytest -q
   ```
3. 提交前跑全量测试（当前 **187 passed** 基线），确保不回归。
4. 提交信息用中文或英文均可，说明"改了什么 + 为什么"。
5. 提交 PR，在描述中按第 2 节同意 CLA，并说明：
   - 改动内容
   - 跑了哪些自检、最后一行结果
   - 是否引入新的第三方材料（若有，按 CLA 第 6 节标注来源与许可）

## 4. 代码约定

- 文档与沟通用**简体中文**；含中文的文件一律 **UTF-8 无 BOM**。
- 评测代码放在独立的 `bench/`，不进桌面默认执行路径。
- **原 Core 项目（`E:/Competition/YAI Agent Core`）为只读上游，不得直接修改**；
  需要改 Core 层逻辑时，在 YoAi 内建本地覆盖层或 fork 副本。
- 不要在源码中硬编码 API key / 凭据；配置从环境变量或 .env 读取。

## 5. 已知限制（贡献前请知悉）

- assistant 类问答是当前弱项（需带上下文的结构化抽取，待专门立项）。
- 进化机制已接线但产品价值未证实，暂停研究中。
- judge 使用 deepseek 而非官方 gpt-4o，评测分数不可与官方榜单直接对比。

这些不是 bug 清单，而是当前研究状态——欢迎针对性贡献，但请先开 issue 讨论方向。

# 第一轮真实智能体测试报告（算里免费 DeepSeek）

> 测试时间：2026-11-21　模型：`deepseek/deepseek-v4.1-flash-1017`（suanli.cn，免费）
> 方式：真实 HTTP API，非脚本/假模型。key 从 Core `.env` 读到内存，不回显/不写盘。
> 目的：此前所有测试都用 ScriptedModel/DemoModel 离线跑，模型接入只做过"直连 HTTP 200
> 返回收到"的探针（`AGENT-PROBE.md`）。本轮第一次用**真模型跑完整智能体链路**。

## 结论

**端到端链路全部跑通**：真模型 → 路由选专家 → 工具调用 → 副作用落盘 → 真实验收 →
证据采集（带真实 usage）→ 归因。免费模型可用，中文回答自然，工具参数正确。

## 测试结果

| # | 场景 | 结果 | 关键证据 |
|---|---|---|---|
| 1 | 连通性探针 | ✅ | `send('只回复四个字：测试收到')` → "测试收到"，usage 91 tokens |
| 2 | 单轮对话 + 路由 + 验收 + 证据 | ✅ | 路由 direct；回答"我可以回答问题和处理任务…"；
  verification=`not_verifiable`（无硬验目标，诚实跳过）；355 tokens；expert_id 落证据 |
| 3 | 单轮工具调用 + 副作用验收 | ✅ | 真模型主动调 `remember_fact{key:咖啡偏好,value:美式}`；
  真实落盘 `{'咖啡偏好':'美式'}`；verification=`verified_success`；1843 tokens |
| 4 | 多轮工具链（记住→回忆） | ✅ | 第一轮 `remember_fact` 落"城市=杭州" verified_success；
  第二轮真模型自己选 `list_facts` 查证并答"杭州"；共 3797 tokens |

## 逐项说明

### 场景 3：真模型工具调用（最关键）
模型不仅正确调用了工具，还自己补了 `tag: 饮食偏好`，说明它理解了工具 schema。
落盘是真实的 `PersonalContext`，不是回执文本。`OutcomeVerifier` 基于真实收据判
`verified_success`，同时状态断言器查了个人事实确认值真的存在（双重确认）。

### 场景 4：partial 不是 bug，是诚实
第二轮"我城市是哪里"验收返回 `partial`。原因：
- 收据器判工具成功（ok）；
- 状态断言器 `make_context_assertion` 只覆盖"记住 X 是 Y"类目标，对"回忆/查询"类
  目标返回 `not_verifiable`；
- `CompositeVerifier` 取较保守结果 → `partial`。

这符合设计原则（无证据不假装成功），但暴露一个真实缺口，见"未完成项"。

## token 消耗（免费额度）

单轮对话 355、单轮工具 1843、两轮工具链 3797，合计约 6000 tokens。
算里 deepseek flash 免费额度当前可用，无 402/429。

## 未完成项 / 缺口

1. **状态断言器只覆盖"记住 X 是 Y"**：回忆/查询类目标返回 `not_verifiable`，
   导致场景 4 只能判 partial。需扩展断言类型（回忆类：目标值应在回答文本中且与事实库一致）。
2. **未跑真实模型的进化链**（M2 `EvolutionEngine.evolve`）：之前用假证据跑通，
   真模型下"归因→候选生成→隔离评测"尚未端到端验证。
3. **未跑真实模型的群聊 L2 协作**：AGENT-PROBE 里 L2 探针是单条 HTTP，
   群内多 peer 用真模型互相对话未跑。
4. Android/桌面外部智能体（L1/L0）不在此轮范围。

## 复现

```bash
cd $YOAI_ROOT
PYTHONPATH="src;$YAI_CORE_SRC" \
  "$CORE_PY" -c "
from yoai.models import SuanliAdapter
a = SuanliAdapter(); print(a.available())
r = a.send('只回复四个字：测试收到'); print(r.ok, r.text, r.meta['usage'])
"
```

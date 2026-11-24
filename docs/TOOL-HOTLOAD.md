# 工具热加载（2026-11-24）

旧会话不用重启进程、不用开新会话，也能用上新工具。

## 背景

此前 YoAi 反馈"会话开始时就固定了工具表，新注册的工具要开新会话才可见"。
核查结论：

1. **Core 的工具注册表是活字典**——每轮 `astream` 前从 registry 现读组装工具
   schema（工具白名单就靠"就地重建 registry._tools"实现，运行中生效已验证）。
   "固定工具表"不是 Core 的硬限制，是 YoAi 构造 agent 时一次注册就不再管。
2. **会话历史本来就是持久化的**（每 session 独立 SqliteStore）——重启进程后
   旧会话自动恢复、历史全在，工具表直接是新的。**"要开新会话"是误解**。
3. `registry.register()` 遇重名报错——热加载必须按名字 diff，只补缺的。

## 实现（全部在 YoAi 侧，内核零改动）

- `YoAiAgent.refresh_tools()`：重建工具表并 diff 注册，返回本次新注册的工具名。
  - registry 缺了已知工具（如被过滤器清场后没补回）→ 补回；
  - 插件目录有新/变更文件 → 加载注册，同名插件工具可热替换；
  - 插件工具与内置工具重名 → **跳过**（不许插件覆盖内核/实操工具）。
- `astream()` 每轮开始前自动调 `refresh_tools()`（异常不反噬主任务；
  无 plugins 目录时零开销，不扫描）。

## 插件约定

目录：`data_dir/plugins/*.py`。桌面端（exe）实际路径：

```
<exe所在目录>/output/sessions/shared/plugins/
```

（开发模式在项目根 `output/sessions/shared/plugins/`。）

每个插件是普通 `.py` 文件（**不受 PyInstaller 冻结影响，exe 下可用**），
二选一导出：

```python
# 方式一：直接给 TOOLS 列表
from yai_core import build_spec

def calc_sum(a: int, b: int) -> int:
    """把两个整数相加。"""
    return a + b

TOOLS = [build_spec(calc_sum)]

# 方式二：给 build_tools() 工厂
def build_tools():
    return [build_spec(calc_sum)]
```

- **新增**：放一个新 `.py` 文件，下一轮对话即可用，无需重启；
- **修改**：改文件内容，下一轮自动热替换（按 mtime 检测）；
- **删除**：删文件后本进程内该工具仍在（注册表不回滚），重启后消失——
  真要立刻禁用，把文件内容改成空 `TOOLS = []` 即可热替换掉。
- 坏插件（语法错误/没导出工具）会被跳过并记住失败时间戳，不反复重试、
  不影响主对话。

## 安全边界

- 插件不能覆盖内置工具（重名直接跳过）；
- 权限走 Core 原生 `AllowlistPolicy`/审批通道——插件工具若不在 auto 白名单，
  调用时照样弹窗确认（桌面端）；
- `build_spec` 注册时经 Core `validate_egress_paths` 校验。

## 测试

`tests/test_tool_hotload.py` 8 项：新增/热替换/工厂导出/坏插件/重名保护/
registry 缺失补回/无目录零开销/astream 自动加载。全量 257 passed。

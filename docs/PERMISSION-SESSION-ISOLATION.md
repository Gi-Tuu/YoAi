# 权限档位按会话独立 —— 端到端验证报告

> 2026-11-25。背景：权限三档控件上线并改为按会话独立后，项目所有者连续追问
> 三个隔离性风险（改 B 会不会锁死 A / 污染 A 的白名单）。本报告把三轮实证
> 验证结果集中留档，避免重复排查。

## 一、三档语义与实现

| UI 档位 | Core `AllowlistPolicy` | 行为 |
|---|---|---|
| 允许完全访问 | `mode=allow_all` | 所有工具自动执行，不弹窗 |
| 智能访问（默认） | `mode=auto` + 22 项白名单 | 只读/记忆类自动放行，写操作弹窗 |
| 手批访问 | `mode=auto` + 空名单 | 每个工具都弹窗确认 |

**按会话独立的存储**（`<data_dir>/config.json`）：

```json
{
  "permission_levels": { "<会话A>": "full", "<会话B>": "manual" },
  "permission_default": "smart"
}
```

- 新会话首次使用时把初始档位固化为自己的，之后与其他会话互不影响
- 兼容旧版全局单值 `permission_level` 配置（作为默认值读取）

**关键陷阱（已修）**：`SessionManager` 的 `agent_kwargs` 里 `policy` 对象是所有
会话**共享的引用**。若直接改当前会话的 policy，会污染模板，导致新会话继承旧档位。
修复：切档/切会话前先 `copy.copy(policy)`，并同步 `core.executor.policy`，
不再改共享模板（`tests/test_permission_levels.py::test_policy_copy_prevents_shared_template_pollution` 守护）。

## 二、验证方法

三轮验证均使用**真实会话数据副本**（`cp -r dist/output <临时目录>`），
通过 `YOAI_DATA_DIR` 指向副本，直接用 `Runtime.handle()` 发协议命令、
读取 `permission.state` 消息、`policy.mode/allowed` 与 `config.json`。
**真实 `dist/output/` 全程未被改动**，每轮结束删除副本。

## 三、验证一：会话改 full 全流程（6 步全通）

真实会话 `977a2f22...`（原项目数据，无 config.json）的副本：

| 步骤 | 操作 | 结果 |
|---|---|---|
| 1 | `hello` | 回 `ready/snapshot/chat.state/permission.state`；档位 `smart`，白名单 22 项；自动固化该会话档位 |
| 2 | `permission.set(full)` | 回 `permission.state(full)`；`mode: auto → allow_all`；白名单清空；config 写入该会话 `full` |
| 3 | 实际决策 | `file_create` = **allow**（写工具自动放行） |
| 4 | 新建会话 | 新会话回 `smart`，`mode=auto`，**未继承**原会话 full；config 两会话分别存档位 |
| 5 | 切回原会话 | 回 `permission.state(full)`，`mode=allow_all`，`file_create=allow` |
| 6 | 最终 config | `{"permission_levels": {"977a...": "full", "c826...": "smart"}}` |

## 四、验证二：改 B 后切回 A —— 是否锁死（6 步全通）

| 步骤 | 状态 |
|---|---|
| 1 | B 改 full 前：`smart`，`auto`，22 项白名单 |
| 2 | B 改 full 后：`full`，`allow_all`，0 项白名单 |
| 3 | 切回 A：`smart`，`auto`，22 项白名单 —— **没被锁死** |
| 4 | A 再改 `manual`：`manual`，`auto`，0 项 —— **切回后仍能改档** |
| 5 | 再切回 B：`full`，`allow_all` —— **B 未被 A 牵连** |
| 6 | config：A=`manual` / B=`full`，双向隔离 |

"锁死"最直接的证伪是第 4 步：切回 A 后仍能正常改档。

## 五、验证三：改 B 后切回 A —— 白名单是否被污染（逐项对比）

| 检查项 | 结果 |
|---|---|
| A 切前白名单 | `auto`，22 项（完整列表见下） |
| B 改 full | B 自己的白名单清空为 0 项 |
| 切回 A 白名单 | `auto`，22 项，**逐项完全相同 = True** |
| `core.policy` 与 `executor.policy` | **同一对象 = True**（无"改了 policy 但执行器用旧的"） |
| A 实际决策 | `file_read=allow`（白名单内）、`file_create=ask`（白名单外） |
| "白名单没被 B 的 full 清空" | **True** |

A 的完整白名单（切前/切后一致）：

```
all_topics, complete_goal, create_goal, events_between, facts_by_tag,
file_list, file_read, file_ro_list, file_ro_read, list_facts, list_goals,
list_tools, now, open_url, recall_fact, recent_events, related_events,
remember_event, remember_fact, summarize_theme, web_fetch, web_search
```

## 六、结论

1. 档位按会话独立生效：改 B 不影响 A，新会话不继承旧会话的设置。
2. 切回 A 后 A 仍可正常改档，**不会锁死**。
3. A 的白名单内容**逐项未被污染**，实际权限决策正确。
4. 共享引用陷阱已用 `copy.copy()` + 同步 `executor.policy` 根治，并有回归测试守护。

每轮验证副本均已删除；真实 `dist/output/` 无 `config.json`，即所有者尚未在 UI
改过档位（首次改档时才写入）。

## 七、相关提交与测试

- `4ec795a`：权限三档控件 + 持久化
- `c8fe431`：改为按会话独立 + 共享引用修复
- `tests/test_permission_levels.py`：4 项测试（三档映射/实际决策/按会话持久化/协议契约）
  + 共享引用污染回归测试
- 全量 `256 passed + 1 skipped`；前端 `11 passed`

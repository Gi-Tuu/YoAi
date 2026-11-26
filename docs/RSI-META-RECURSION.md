# R4 元递归：进化策略本身的版本化（2026-11-26）

> YoAi 侧扩展，Core 零改动。元策略只管阈值/权重，**不改安全边界**。

## 定义

元策略是一组可被版本化的 RSI 参数：

```
min_validation_samples / min_trial_samples
weak_gap / watch_gap
weak_rework / watch_rework
cost_ratio / cooldown_days
capability_ratio / environment_ratio
```

存储：`<data_dir>/evolution/meta_policies.jsonl`，当前生效版本写在 `meta_active.json`。

## 规则

- 初始版本为 v1；
- `rsi.meta_propose` 只在证据足够时提出新版本：
  - 回滚率 >30%：收紧 weak_gap / cost_ratio / weak_rework；
  - 连续 ≥3 次隔离验证 improved 但 0 晋升：适度放宽 min_trial_samples / weak_gap；
- 调整幅度受硬界限制：weak_gap ≤0.25、cost_ratio ≥1.0、weak_rework ≥0.10；
- 新版本写入档案和 `rsi_meta_propose` 报告，状态为候选，**不会自动生效**；
- `rsi.meta_approve(version, approved_by)` 必须记录批准人，才切换到 active；
- active 元策略驱动 R3Promoter 与 RollbackMonitor 的阈值。

## 不可元进化

以下边界元策略不能改：
- 审计日志；
- 回滚条件中的 verified_failure；
- 人工批准要求；
- retired 不可复活；
- 签名校验、依赖安装隔离、权限审批。

## 桌面页

左侧「元策略」页展示：
- 当前生效版本与全部阈值；
- 版本历史与提案理由；
- 「生成候选提案」与「批准此版本」按钮。

## 协议

`rsi.meta_status` / `rsi.meta_propose` / `rsi.meta_approve`。

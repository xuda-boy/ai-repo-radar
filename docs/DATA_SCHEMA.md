# 数据说明

私有数据仓的 `data/` 使用便于审阅和 Git diff 的追加式布局：

```text
data/
├── reports/YYYY/MM/DD.json
├── snapshots/YYYY/MM/DD.jsonl
├── feedback/events/<UUID>.json
├── outbox/<UUID>.json              # 本地忽略，不提交
├── profile/interest.json
└── metadata/repositories.json
```

## 日报

`DailyReport` 包含日期、生成时间、正常/降级状态、模型错误分类、最多 8 个 `Recommendation` 和过滤/配额统计。每个推荐保留公开仓字段、推荐类型、增长证据、评分拆分、规则推荐原因、可选中文摘要和快速开始。

## Star 快照

每日 `.jsonl` 每个仓库一行，主键语义为 `(observed_at, repo_full_name)`。重复追加相同主键会跳过。增长计算选每天最后一次观测，并在目标时间附近寻找 24 小时和 7 天基线。

## 反馈事件

事件字段包括 `event_id`、仓库、动作、topics、创建时间、次日 `effective_date`、来源日报、同步状态和可选的 `reverts_event_id`。四种原始动作的默认 Topic 调整：

| 动作 | 调整 |
|---|---:|
| `more_like` | `+0.12` |
| `save` | `+0.05` |
| `irrelevant` | `-0.12` |
| `known` | `0.00` |
| `revoke` | 原动作的反向调整 |

`revoke` 必须通过 `reverts_event_id` 指向一条非撤回事件；它追加一条补偿记录而不覆盖原 JSON。单个 Topic 权重限制在 `[-1, 1]`。同一 UUID 被多次读取只应用一次。

## SQLite

SQLite 包含 reports、recommendations、snapshots、feedback_events、saved 和 interest_profile 表，只用于查询。运行 `rebuild-cache` 会从上述 JSON 重建整个文件，不进行增量迁移或把 SQLite 提交到 Git。

## 保留

- 日报、反馈事件：长期保留。
- Star 快照：v0.1.0 写入全部历史；运维层目标保留 1 年，删除策略应在后续版本以独立、可审计任务实现。
- 元数据、兴趣画像：保留当前可重建版本。

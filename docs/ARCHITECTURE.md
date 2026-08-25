# 架构说明

## 边界

`ai-repo-radar` 是单用户、本地查看、GitHub Actions 调度的单体应用。它不提供公网服务、账户系统、团队权限、在线数据库或模型训练。

## 主链路

1. `GitHubClient` 使用五组官方 Search API 查询并合并候选，随后读取优先候选的公开 README 与最新 Release。
2. `filters.py` 先执行硬质量门槛；失败原因作为代码计数进入日报统计。
3. `snapshots.py` 从每日 Star 快照计算 24 小时、7 天、相对增长、低基数保护和加速信号；历史不足时明确标为估算。
4. `scoring.py` 使用纯函数生成质量、兴趣、增长、健康和新颖性分数。模型不参与名次。
5. `pipeline.py` 根据冷启动或 5/2/1 配额选择最多 8 项。
6. `MiniMaxClient` 只把最终公开项目的名称、描述、语言、topics 和 README 片段发送给 MiniMax-M3，解析中文摘要与快速开始。
7. `JsonDataStore` 原子写日报、画像与元数据，并追加 Star 快照和 UUID 反馈事件。
8. `cache.py` 可从 JSON 全量重建 SQLite，Dashboard 只读该派生视图。

## 两仓拓扑

公开仓维护唯一实现与 reusable workflow；私有仓只维护入口 workflow、配置和事实数据。被调用 workflow 在调用方权限上下文运行：

- `actions/checkout` 首先签出调用方私有仓，因此默认 `github.token` 只能写该仓。
- 再按 release tag 签出公开实现，避免运行移动的默认分支。
- 任务只 `git add` 私有仓的 `data/`，不提交配置或缓存。
- 无需让公开仓拥有私有仓 PAT。

## 事实源与缓存

JSON 是事实源。SQLite 使用临时文件完整构建，成功后原子替换旧缓存。删除 SQLite 不影响任何长期数据。正常日报默认不可覆盖；只有显式 `--replace-report` 才允许替换，且降级日报永远不能覆盖已存在的正常日报。

## 反馈一致性

每次反馈先生成 UUID 并写本地 outbox。兴趣画像按 `effective_date` 重放事件，`applied_event_ids` 保证同一事件不会重复影响权重。同步时：

1. 验证数据目录位于带 `.ai-repo-radar-private` 标记的 Git 仓。
2. 要求工作树没有无关更改，fetch 并 rebase 当前分支。
3. 把 outbox 事件复制为 `feedback/events/<UUID>.json` 并提交。
4. push 成功后才删除 outbox；失败则保留并标为 `pending_retry`。

## 模块地图

| 模块 | 职责 |
|---|---|
| `config.py` | TOML、默认权重与本地监听安全约束 |
| `providers/github.py` | GitHub REST、重试、限流与公开数据映射 |
| `providers/minimax.py` | MiniMax-M3 公开上下文、验证与降级 |
| `filters.py` / `scoring.py` | 可解释确定性推荐 |
| `snapshots.py` | Star 时序证据 |
| `feedback.py` | 次日生效 Topic 权重 |
| `storage.py` / `cache.py` | JSON 事实层与 SQLite 视图 |
| `sync.py` | 私有仓 outbox 同步安全门 |
| `web.py` | FastAPI/Jinja/HTMX 本地工作台 |
| `cli.py` | 固定样例、每日任务、同步、服务与诊断 |

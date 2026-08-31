# 运维手册

## GitHub Actions 首跑

1. 公开仓 CI 全绿后创建新的不可变 release tag。
2. 私有数据仓保持 `main` 默认分支，并确认 `.ai-repo-radar-private` 已提交。
3. 修改私有仓 workflow 的 `your-github-owner`。
4. 新增私有 Actions Secret `MINIMAX_API_KEY`；不需要自建 `GITHUB_TOKEN`。
5. Actions → Daily AI Repo Radar → Run workflow。
6. 检查 Summary、`data/reports/...json` 和 `data/snapshots/...jsonl` 后再保留 schedule。

## 补跑

定时任务使用 `daily --skip-existing`：同一天已有日报时会在任何网络调用前成功退出，因此可安全安排多个补跑时段。如果任务在 JSON 写入前失败，后续时段会再次尝试；如果确实要替换正常日报，先审阅差异，再在手动 workflow 中勾选 `force`，它会显式使用 `daily --replace-report`。定时 workflow 永不默认覆盖。

## MiniMax 降级

以下问题会保存降级日报并保持任务成功：缺 Key、401/403、429、5xx、超时、网络失败、内容安全拒绝和无效 JSON。页面显示“AI 中文摘要暂不可用”，但规则排序、公开描述和增长证据仍存在。

无效 JSON、输出截断、字段缺失、英文摘要或项目未补齐会自动重试；重试时降低随机度并逐步缩小批次，只请求仍缺失的项目。已通过中文和字段校验的结果会被保留。Actions 日志只显示安全诊断信息（尝试次数、错误代码、完成原因、请求数和通过数），不会保存 MiniMax 原始回复或 Secret。

修复额度或 Secret 后，如当天只有降级日报，可再次手动运行。事实层允许正常结果替换当日降级结果。

## GitHub 或数据失败

GitHub 限流、持续 5xx、网络失败或数据写入错误会使 workflow 失败，不生成不可信日报。先检查 Action 日志中的错误类别；客户端不会打印请求头或 Secret。

## 本地同步冲突

正式仪表盘顶部状态面板会列出待同步反馈；点击“立即同步到私有仓”会执行与 `sync-data` 相同的安全流程。样例目录只显示“仅本地”，不会推送。

正式仪表盘还会默认每 5 分钟执行一次 pull-only 检查：只拉取云端日报并重建派生缓存，不会自动提交或推送反馈。顶部“立即检查更新”执行同一流程；发现新日报后页面自动重载。若状态为“等待今日日报”，说明云端定时任务尚未产出当天报告；“数据已过期”则应同时检查 Actions 运行记录、网络和本地 Git 工作树。

同步要求私有仓没有无关工作树修改。若页面或 `sync-data` 提示失败：

1. 在私有仓运行 `git status --short`。
2. 人工确认并提交或暂存你自己的改动。
3. 完成 rebase/merge 后再次运行 `sync-data`。

不要删除 `data/outbox/` 来“修复”冲突；它是尚未确认推送的本地反馈。

## 缓存恢复

```powershell
uv run ai-repo-radar rebuild-cache `
  --data-dir D:\Github\ai-repo-radar-data\data `
  --database D:\Github\ai-repo-radar-data\.cache\radar.sqlite3
```

数据库文件可直接删除后重建。若 JSON 自身校验失败，应恢复或修正对应 Git 提交，而不是跳过坏记录。

## 观察首周

首 7 天增长中可能出现估算状态，这是设计行为。每天检查：候选数、过滤数、推荐数、MiniMax 状态、outbox 状态和日报 Git diff。第 8 天确认兴趣画像能从反馈 UUID 重建，并观察 5/2/1 空位是否遵守“质量不足不补位”。

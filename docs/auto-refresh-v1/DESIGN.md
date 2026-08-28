# DESIGN

## Product Type

- Type: 本地数据看板 / 开源情报工作台
- Main business object: 每日推荐报告及 Git 同步状态
- Selected recipe: Data Dashboard
- Reference files: data-dashboard 与 SaaS dashboard UI 规则
- Selected patterns: Tremor KPI 状态层级、loading-empty-error 状态集
- User role: 项目所有者
- Primary task: 无需重启即可取得云端新日报，并可立即检查

## Pattern Commitments

| Pattern | Where It Applies | What To Imitate | What Not To Copy |
|---|---|---|---|
| Tremor KPI chart grid | 顶部任务状态 | 时间范围、数据源、新鲜度优先 | React 组件和额外依赖 |
| Loading empty error set | 更新表单与状态轮询 | 就地 loading、错误、禁用与重试 | 只有 toast 的反馈 |

## Design Goals

- 自动每 5 分钟只读拉取私有仓，并在有变更时原子重建 SQLite。
- 用户随时可点“立即检查更新”，新日报到达后页面自动重载。
- 样例、昨日等待、过期、失败和并发状态均可解释，旧数据永不因失败被覆盖。

## Screen Structure

- Navigation: 不变。
- Main content: 不变。
- Secondary panel / details: 顶部任务状态弹层新增“日报更新”区。
- Primary action: “立即检查更新”。
- Risk / confirmation area: “反馈同步”保留独立显式按钮。

## Component Plan

| Component | Purpose | Desktop Behavior | Mobile Behavior |
|---|---|---|---|
| System status button | 显示最高优先级的新鲜度 | 顶栏紧凑标签 | 最大宽度截断，弹层给完整文案 |
| Data refresh panel | 显示日报日期、检查时间、结果 | 位于模型与反馈之间 | 单列、按钮 44px |
| Refresh form | POST 拉取，不推反馈 | HTMX 局部更新 | 相同行为 |
| Status poller | 发现后台取得新日报 | 每 60 秒轻量查询 | 页面可见时查询 |

## State Plan

- Loading: HTMX 请求期间禁用按钮并显示“检查中…”。
- Empty: 无日报时显示未生成。
- Error: 更新失败、保留旧数据、隐藏底层异常。
- Disabled: 非私有数据目录禁用更新。
- Hover: 沿用现有橙色主操作。
- Selected: 弹层展开态保持键盘可访问。
- Needs human review: 反馈推送不进入自动轮询。

## Visual System

- Typography: 沿用现有中文无衬线与 mono 辅助信息。
- Color: moss 成功、ochre 等待、orange/red 失败。
- Spacing: 8/10/12px。
- Radius / shadow / border: 4px 控件、现有弹层阴影。
- Density: 不增加主页面高度。

## Responsive Plan

- Desktop viewport: 1440×1000。
- Mobile viewport: 390×844。
- Expected mobile layout: 顶部状态弹层单列，状态详情换行。
- Overflow prevention: 文案 `overflow-wrap:anywhere`，按钮宽 100%。

## Safety Plan

- Customer data: 不涉及。
- Permissions: 不修改。
- Secrets: 不返回原始 Git 错误。
- Bulk send / export / writeback: 自动刷新调用 pull-only；反馈 push 仍由现有表单触发。
- External links: 不新增。
- Human confirmation: 用户已确认本地实现和重启；不自动 commit/push 公开代码。

## Implementation Notes

- Files to edit: `sync.py`、`web.py`、`cli.py`、`config.py`、`base.html`、新增数据状态 partial、`app.css`、`app.js`、配置/README、测试。
- Files to avoid: 排名、GitHub 召回、MiniMax、报告事实模型与私有数据内容。
- Existing design patterns to preserve: Signal Ledger 外壳、状态弹层、HTMX CSRF 与原子缓存重建。
- Pattern files to keep open while editing: selected dashboard and state pattern docs。
- License / source constraints: 仅采用结构思想，无新增前端依赖或复制源码。

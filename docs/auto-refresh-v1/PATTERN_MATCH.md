# PATTERN MATCH

## Summary

- Product type: 本地数据看板 / 开源情报工作台
- Main business object: 每日 GitHub AI 项目日报及其本地同步状态
- Selected recipe: `recipes/data-dashboard.md`
- Selected patterns: `dashboard/tremor-kpi-chart-grid`、`states/loading-empty-error-set`
- Patterns deliberately not selected: `data-table/faceted-filter-table`；本次不新增筛选或明细表，不应改动现有推荐列表结构。

## Product Type Decision

| Signal | Evidence | Decision Impact |
|---|---|---|
| User role | 项目所有者每天查看推荐 | 更新状态必须首屏可见且可解释 |
| Primary task | 判断数据是否最新，并在必要时立即拉取 | 在现有任务状态弹层内提供主操作 |
| Data object | 日报日期、自动检查时间、Git 拉取结果 | 不虚构 KPI，只展示可验证状态 |
| Risk level | 私有 Git 仓与本地反馈 | 自动任务只拉取；反馈推送仍需明确点击 |
| Mobile need | 现有 390px 工作台已支持移动端 | 新按钮保持 44px，状态文案允许换行 |

## Recipe Selection

- Recipe: Data Dashboard
- Why this recipe: 页面核心是日报时效、趋势证据和行动入口。
- References read: `data-dashboard-ui.md`、`saas-dashboard-ui.md`、`data-dashboard-notes.md`
- Checklists read: UI audit、visual QA、product risk、mobile responsive

## Pattern Selection

| Pattern | Role In This Redesign | Why Selected | What To Imitate | What Not To Copy |
|---|---|---|---|---|
| Tremor KPI chart grid | Main | 强调时间范围、刷新状态、数据源状态 | 状态先于详情、指标口径清楚 | React/Tremor 组件和视觉品牌 |
| Loading empty error set | State | 更新动作需要完整状态矩阵 | 按钮级 loading、明确错误与重试 | 泛化占位文案或只用 toast |

## Business Object Mapping

| Target Project Object | Pattern Object | Fields / Components To Map | Notes |
|---|---|---|---|
| 最新日报 | KPI / data source state | 日报日期、新鲜度、数据模式 | 样例与真实数据必须区分 |
| Git 拉取 | Inline loading action | 上次检查、自动间隔、结果消息 | UI 不显示路径、remote 或原始 Git 错误 |
| 反馈 outbox | Existing state panel | 待同步数量、显式推送按钮 | 不纳入自动拉取副作用 |

## State Coverage From Patterns

- Loading: “检查中…”且按钮禁用。
- Empty: 尚无日报时说明如何生成。
- Error: 保留旧数据，给出检查网络/Git 凭据的行动建议。
- Disabled: 样例或普通目录说明不能自动拉取。
- Hover: 延续现有橙色按钮反馈。
- Selected: 状态弹层继续使用 `aria-expanded`。
- Needs human review: 反馈推送继续由用户明确点击。

## License And Source Risk

| Pattern | Source | License | Risk / Required Action |
|---|---|---|---|
| Tremor KPI chart grid | Tremor | Apache-2.0 | 只采用信息层级，不复制组件源码 |
| Loading empty error set | Kit internal pattern | project-local | 可直接适配现有 Jinja/HTMX |

## Human Confirmation Required

- Customer data: 不涉及。
- Permissions: 不修改。
- Bulk send / export / writeback: 自动流程不推送；反馈写回保留显式操作。
- External links: 不新增。
- Delete / irreversible actions: 不涉及。
- Secrets / API keys / internal links: UI 和日志摘要不得回显。
- Final copy / dates / recipients: 日期来自日报事实，不对外发布。

## Decision

- Proceed with selected patterns: 是。
- Need more source verification: 否；复用项目现有样式与同步实现。
- Must avoid: 自动推送反馈、泄露私有仓路径、用 GET 触发写操作、并发 Git 操作。

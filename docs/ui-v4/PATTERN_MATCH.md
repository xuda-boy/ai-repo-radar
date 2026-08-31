# Pattern Match

## Product and recipe

- Product type: 本地 AI 开源情报 Dashboard / 项目发现工作台。
- Selected recipe: Data Dashboard。
- Primary object: 每日推荐仓库，而不是通用 KPI 或营销内容。

## Selected patterns

| Pattern | Adopted behavior | Adaptation |
|---|---|---|
| shadcn dashboard shell | 持久侧栏、状态顶栏、主工作区 | 保持服务端 Jinja，不引入 React 组件依赖 |
| Tremor KPI chart grid | 四项一组的业务概览与趋势证据 | KPI 只展示推荐、增长、结构、中文增强 |
| CRM list-detail | 左侧对象清单控制右侧粘性详情 | 对象改为 GitHub 仓库、日报与收藏项目 |

## Rejected directions

- 不继续使用旧版报纸式米色画布与密集等宽字体。
- 不使用整页重复大卡片流，避免失去对象比较效率。
- 不加入无业务含义的活跃用户、转化率或营销模块。
- 不隐藏模型降级、样例数据、待同步与估算证据。

# UI AUDIT

## Summary

- Product type: 本地数据看板
- User role: AI Repo Radar 项目所有者
- Primary task: 看到最新日报并理解自动更新是否正常
- Current UI quality: 推荐阅读体验成熟，但“数据已同步”实际只描述反馈队列，无法表达日报新鲜度或触发拉取。

## Findings

| Priority | Area | Issue | Evidence | Recommended Fix |
|---|---|---|---|---|
| P0 | 数据源 | 页面刷新只读 SQLite，不会拉取私有仓 | 8766 长期停留在固定 8 月 25 日样例 | 私有模式后台定时 pull 并原子重建缓存 |
| P1 | 顶部状态 | “数据已同步”混淆日报与反馈状态 | 状态弹层只有 GitHub/模型/反馈三行 | 独立显示日报新鲜度、上次检查和自动间隔 |
| P1 | 操作入口 | 无待反馈时原按钮禁用，不能检查新日报 | `sync-submit` 取决于 `pending_sync` | 新增始终可用的“立即检查更新” |
| P1 | 状态完整度 | 拉取缺 loading/no-change/error/busy | 现有端点仅面向反馈同步 | 增加完整结果状态并保留旧缓存 |
| P2 | 实时性 | 后台更新后已打开页面不会变化 | 浏览器无日报版本轮询 | 轻量轮询状态，发现新日期后自动重载 |

## Information Architecture

- Current structure: 顶部日期 + 综合状态按钮 + 状态弹层。
- Missing structure: 日报数据源状态与拉取操作。
- Suggested structure: 日期 → 综合新鲜度 → 日报更新区 → 模型状态 → 反馈同步区。

## Component Review

- Navigation: 保持不变。
- Tables / lists / cards: 保持不变。
- Forms / inputs: 新增带 CSRF 的 POST 更新表单。
- Buttons / actions: 更新与反馈同步分开，避免副作用混淆。
- Status indicators: 新增今日、等待、过期、样例、失败、检查中。

## Visual Review

- Typography: 复用 11.5–13px 状态字号。
- Color: 绿色=今日，赭色=等待/样例，橙红=过期/失败。
- Spacing: 延续弹层 8/10/12px 节奏。
- Borders / shadows / radius: 不新增卡片阴影，沿用 4–6px 圆角。
- Density: 在现有弹层中增加紧凑区块，不扩展主画布。

## State Coverage

- Loading: 按钮替换为“检查中…”。
- Empty: “尚无日报”。
- Error: “更新失败，当前数据未被覆盖”。
- Disabled: 样例/普通目录说明自动更新不可用。
- Hover: 使用现有按钮 hover。
- Selected: 现有弹层展开态保持。

## Mobile Review

- Layout: 弹层保持单列。
- Text overflow: 状态详情允许换行。
- Button size: 44px。
- Horizontal scroll: 不新增宽表格。
- Fixed bars / safe area: 不新增固定元素。

## Risk Review

- Customer data: 无。
- Permissions: 无修改。
- Secrets: 错误文案不回显命令输出、路径和凭据。
- Bulk send / export / writeback: 自动任务只拉取；反馈推送仍为显式按钮。
- External links: 无新增。
- Human confirmation needed: 已由用户明确授权实现与本地重启；后续推送公开仓仍需单独授权。

## Decision

- Proceed with redesign: 是。
- Must fix before delivery: P0/P1 全部完成并测试。
- Optional follow-up: 未来可增加 Windows 开机自启，但不在本次范围。

# AI Repo Radar - Repository Instructions

本文件是本仓库的项目级工作约束。开始任何任务前，先阅读本文件、`README.md`，再检查当前 Git 状态和与任务直接相关的代码、测试及文档。

## 项目边界

- 当前仓库 `ai-repo-radar` 是公开代码仓，保存 Python 实现、固定样例、测试、公开工作流和文档。
- 相邻仓库 `D:\Github\ai-repo-radar-data` 是私有事实仓，只保存真实日报、快照、反馈、兴趣画像和私人配置；不得把这些内容复制到公开仓。
- 主入口为 `src/ai_repo_radar/cli.py`，核心链路依次位于 GitHub/MiniMax provider、pipeline、storage/cache、sync 和 web 模块。
- 私有 JSON 是事实源，SQLite 是可删除重建的派生缓存；Dashboard 必须继续只监听 `127.0.0.1`。
- 不得提交 Token、API Key、`.env`、私人日报、SQLite、outbox 或可识别用户兴趣的数据。

## 两条硬性规定

1. **每次改动后必须创建对应的 Git commit。** 一个 commit 只包含一个完整、可验证的功能或修复；不得混入无关重构、格式化或清理。提交前检查 diff，提交后核对 commit 和工作树状态，便于使用 `git revert <commit>` 安全回滚。
2. **每次改动后必须编写或更新测试，交付前确保所有测试和验证通过。** 测试必须覆盖本次行为变化或回归路径；只有文档或仓库规则发生变化时，也要增加或更新相应的自动化验证。若任何必需验证无法运行，不得声称完成，必须明确说明未验证项及原因。

## 实施流程

1. 运行 `git status --short`，保护用户已有改动；不要修改任务范围外的文件。
2. 先复现问题或建立失败测试，再做解决当前问题所需的最小改动。
3. 复用现有模型、模块和业务规则，不复制实现，不做推测性抽象。
4. 运行下面的完整交付验证；失败时先修复，再提交。
5. 使用清晰的 Conventional Commit 风格提交，例如 `feat: ...`、`fix: ...`、`test: ...`、`docs: ...`。
6. 用户要求发布或同步时，将 commit 推送到 GitHub，并核对远端分支或 CI；未成功推送时必须明确告知。

## 必需验证

在仓库根目录执行：

```powershell
uv sync --all-groups
uv run ruff check src tests scripts
uv run pytest --cov=ai_repo_radar --cov-report=term-missing
uv run python scripts/privacy_audit.py
uv build
git diff --check
```

涉及以下范围时还需增加专项验证：

- Dashboard/UI：使用真实路由完成桌面和窄屏浏览器检查，验证交互、无横向溢出及错误/空状态。
- GitHub Actions：解析 YAML，核对固定公开版本、最小权限、Secret 边界及幂等补跑。
- 私有数据同步：验证失败不丢 outbox、不覆盖正常日报、不向公开仓泄露私人事实。
- 数据模型或 schema：验证旧事实可读取、追加式历史不被改写、SQLite 可从 JSON 完整重建。

## 完成交付

交付说明必须包含：改了什么、为什么、对应 commit、实际运行的验证及结果、剩余风险或未验证项。仓库必须保持可解释、可回滚、可从 GitHub 恢复。

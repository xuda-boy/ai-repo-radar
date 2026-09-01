# UI DELIVERY REPORT

## Summary

- Product type: SaaS project discovery dashboard.
- Recipe: SaaS dashboard.
- Patterns used: shadcn dashboard shell; loading/empty/error state set.
- What changed: save is now an independent toggle while “more like / irrelevant / known” remain mutually exclusive; every persisted action is solid purple and appears in the named helper text.
- Current status: interaction and responsive QA passed.

## Files Changed

| File | Purpose |
|---|---|
| `src/ai_repo_radar/cache.py` | Projects every active, non-retracted feedback event for a report |
| `src/ai_repo_radar/web.py` | Retracts only the save or preference/status axis and supplies all selected actions |
| `src/ai_repo_radar/templates/partials/feedback_bar.html` | Renders one or two selected buttons, badges and accessible names |
| `tests/test_storage_cache.py` | Verifies both active axes survive cache rebuild |
| `tests/test_web.py` | Verifies dual selection, preference replacement and per-axis cancellation |
| `docs/DESIGN_SYSTEM.md` | Records the FeedbackBar visual-state contract |

## Before / After

| View | Before | After |
|---|---|---|
| Desktop | One active action replaced every other action | Save and one preference/status action can both remain selected |
| Mobile | One active action replaced every other action | Same two-axis behavior in the existing two-column grid |

Before this change, clicking save retracted “more like / irrelevant / known”, and clicking any of those retracted save. After the change, the active projection and UI can hold save plus exactly one preference/status signal, while each selected button remains visually explicit.

## QA Result

- Desktop screenshot: generated at 1440 × 1000 from the fixed public sample.
- Mobile screenshot: generated at 390 × 844 from the fixed public sample.
- QA report: `.local/feedback-dual-select-after/UI_QA_REPORT.md`.
- Visual scorecard: `VISUAL_SCORECARD.md`.
- Average visual score: 4.9 / 5.
- Passed: no blank risk, horizontal scroll, text overflow or small buttons on desktop or mobile.
- Interaction: “更多此类 + 收藏” produced two selected buttons; switching to “不相关” kept save; clicking “不相关” again kept only save; later cancelling save kept “已了解”.
- Empty state: after cancelling save, the real `/saved` route showed “还没有收藏项目”.
- Accessibility: each selected state exposes `aria-pressed=true`, a named `aria-label` and visible text, so it does not depend on color alone.

## Improvements

- Visual hierarchy: the primary color communicates every active state, including two simultaneous selections.
- Components: each active button includes a compact “已选” badge and the helper lists both labels.
- States: default, hover, focus, one/two selected, submitting and independently cancelled are distinct.
- Mobile responsiveness: the existing two-column grid and four 44 px targets are preserved; live 390 px inspection found no horizontal overflow.
- Risk controls: no private dashboard screenshot or external write was used during QA.

## Human Review Required

- No high-risk human confirmation gate applies to this local, reversible feedback-state presentation change.

## Remaining Follow-Ups

- None for this scope.

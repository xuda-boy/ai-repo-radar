# UI AUDIT

## Summary

- Product type: SaaS project discovery dashboard.
- User role: developer reviewing eight daily repository recommendations.
- Primary task: understand whether a repository is saved and which preference/status signal is active, then change either state confidently.
- Current UI quality: functional but visually misleading in the selected state.

## Findings

| Priority | Area | Issue | Evidence | Recommended Fix |
|---|---|---|---|---|
| P1 | Feedback actions | “更多此类” is always solid purple even when `aria-pressed=false` | Browser computed style: unselected first button `rgb(91, 92, 226)` while selected “收藏” is only pale purple | Make every default action neutral and reserve the solid primary style for the active action |
| P1 | Selection copy | The helper says a choice exists but does not name it | “已选择 · 再次点击取消…” | Show `当前已选：<动作>` and an in-button “已选” badge |
| P2 | Keyboard state | Focus relies on browser defaults | No dedicated feedback focus rule | Add a visible `:focus-visible` ring |
| P1 | Feedback model | A save replaces “more like”, “irrelevant” or “known”, although saving and recommendation preference answer different questions | Server retracts every active event before writing any new action | Keep save as an independent toggle; keep only the other three mutually exclusive |

## Component And State Review

- Navigation, project list and detail hierarchy stay unchanged.
- Feedback actions are one independent save toggle plus a mutually-exclusive preference/status group, implemented with four submit buttons.
- Default, hover, one-selected, two-selected, focus, submitting and independently cancelled states must be visually distinct.
- Selection must use both color and text, not color alone.

## Mobile Review

- Keep the existing two-column action grid and 44 px minimum height.
- The compact “已选” badge must not cause horizontal overflow or clipped labels.
- No hover-only information is introduced.

## Risk Review

- No customer data, permission, secret, bulk-send, export, delete or public sharing change.
- Browser screenshots and reports must use the fixed public sample, never the private data repository.

## Decision

- Proceed with a scoped state-style repair.
- Must verify save + preference dual selection, preference replacement, and independent repeat-click cancellation on desktop and 390 px layouts.

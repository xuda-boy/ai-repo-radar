# UI AUDIT

## Summary

- Product type: SaaS project discovery dashboard.
- User role: developer reviewing eight daily repository recommendations.
- Primary task: understand which feedback is currently active and change or cancel it confidently.
- Current UI quality: functional but visually misleading in the selected state.

## Findings

| Priority | Area | Issue | Evidence | Recommended Fix |
|---|---|---|---|---|
| P1 | Feedback actions | “更多此类” is always solid purple even when `aria-pressed=false` | Browser computed style: unselected first button `rgb(91, 92, 226)` while selected “收藏” is only pale purple | Make every default action neutral and reserve the solid primary style for the active action |
| P1 | Selection copy | The helper says a choice exists but does not name it | “已选择 · 再次点击取消…” | Show `当前已选：<动作>` and an in-button “已选” badge |
| P2 | Keyboard state | Focus relies on browser defaults | No dedicated feedback focus rule | Add a visible `:focus-visible` ring |

## Component And State Review

- Navigation, project list and detail hierarchy stay unchanged.
- Feedback actions are a single-select group implemented with four submit buttons.
- Default, hover, selected, focus, submitting and cancelled states must be visually distinct.
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
- Must verify first click, replacement and repeat-click cancellation on desktop and 390 px layouts.

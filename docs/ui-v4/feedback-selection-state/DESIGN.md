# DESIGN

## Product Type

- Type: SaaS project discovery dashboard.
- Main business object: repository feedback choice.
- Selected recipe: SaaS dashboard.
- Selected patterns: shadcn dashboard shell; loading/empty/error state set.
- Primary task: identify and change the one active feedback choice.

## Design Goals

1. Only the action actually stored as active may look selected.
2. The selected state must remain clear without relying on color alone.
3. Clicking the selected action again must visibly return all actions to neutral.

## Component Plan

| Component | Purpose | Desktop Behavior | Mobile Behavior |
|---|---|---|---|
| Feedback helper | State summary | `当前已选：收藏 · 再次点击可取消` | Wraps above actions |
| Feedback action | Submit one signal | Neutral by default; solid primary when selected | Same state, 44 px target |
| Selected badge | Redundant state cue | Compact “已选” pill inside active button | Remains inline without overflow |

## State Plan

- Default: white surface, neutral border and label.
- Hover: primary-soft background and primary text.
- Focus: two-pixel primary outline with offset.
- Selected: solid primary background, white text/icon, stronger border and subtle shadow, plus “已选”.
- Submitting: preserve existing HTMX disabled/swap feedback.
- Cancelled: server response removes selected class and restores the default helper.

## Responsive And Safety Plan

- Desktop: preserve four equal columns.
- Mobile: preserve two equal columns and 44 px minimum targets.
- Prevent badge wrapping by using compact typography and nowrap inside each action.
- Preserve CSRF, local-origin validation, append-only facts and all existing server behavior.

## Implementation Notes

- Edit `templates/partials/feedback_bar.html`, `static/app.css` and focused web tests only.
- Reuse existing primary tokens; do not copy upstream code.
- Run isolated sample interaction, desktop/mobile visual audit and the complete repository validation before commit.

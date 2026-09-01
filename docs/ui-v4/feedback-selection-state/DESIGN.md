# DESIGN

## Product Type

- Type: SaaS project discovery dashboard.
- Main business object: repository save state plus recommendation preference/status state.
- Selected recipe: SaaS dashboard.
- Selected patterns: shadcn dashboard shell; loading/empty/error state set.
- Primary task: save a repository independently from choosing one of “more like / irrelevant / known”.

## Design Goals

1. Only actions actually stored as active may look selected; up to two actions can be active.
2. The selected state must remain clear without relying on color alone.
3. Clicking save again cancels only save; clicking the active preference/status action cancels only that axis.
4. Choosing another preference/status action replaces the previous one without changing save.

## Component Plan

| Component | Purpose | Desktop Behavior | Mobile Behavior |
|---|---|---|---|
| Feedback helper | State summary | `当前已选：更多此类、收藏 · 再次点击相应项可取消` | Wraps above actions |
| Feedback action | Submit one signal | Neutral by default; solid primary when selected | Same state, 44 px target |
| Selected badge | Redundant state cue | Compact “已选” pill inside active button | Remains inline without overflow |

## State Plan

- Default: white surface, neutral border and label.
- Hover: primary-soft background and primary text.
- Focus: two-pixel primary outline with offset.
- Selected: one or two solid primary actions with white text/icon, stronger border and subtle shadow, plus “已选”.
- Submitting: preserve existing HTMX disabled/swap feedback.
- Cancelled: server response removes only the clicked axis; the other selected action stays visible.

## Responsive And Safety Plan

- Desktop: preserve four equal columns.
- Mobile: preserve two equal columns and 44 px minimum targets.
- Prevent badge wrapping by using compact typography and nowrap inside each action.
- Preserve CSRF, local-origin validation and append-only facts. Model active state as two axes without weakening audit history.

## Implementation Notes

- Edit the feedback cache projection, web handler/context, feedback template, documentation and focused tests only.
- Reuse existing primary tokens; do not copy upstream code.
- Run isolated sample interaction, desktop/mobile visual audit and the complete repository validation before commit.

# PATTERN MATCH

## Summary

- Product type: SaaS / project discovery dashboard.
- Main business object: one repository recommendation with an independent save toggle and one optional preference/status choice.
- Selected recipe: `recipes/saas-dashboard.md`.
- Selected patterns: `app-shell/shadcn-dashboard-shell`, `states/loading-empty-error-set`.
- Patterns deliberately not selected: table, CRM, settings, chart and decorative micro-interaction patterns; this change is limited to one action state.

## Product Type Decision

| Signal | Evidence | Decision Impact |
|---|---|---|
| User role | A developer reviewing daily AI projects | Feedback must be readable at a glance |
| Primary task | Save a project independently while recording, cancelling or replacing one recommendation signal | Both active axes must be unmistakable |
| Data object | Repository + save toggle + preference/status choice | Use one independent toggle plus one mutually-exclusive group |
| Risk level | Local append-only feedback write | Preserve audit history and immediate confirmation |
| Mobile need | The dashboard has a 390 px layout | Keep 44 px targets and two-column wrapping |

## Pattern Selection

| Pattern | Role | What To Imitate | What Not To Copy |
|---|---|---|---|
| shadcn dashboard shell | Main | Stable neutral controls with one explicit selected state | React components, branding or shell structure |
| loading empty error set | State | Selected changes background, border and visible status text | Unrelated loading or empty components |

## Business Object Mapping

| Target Project Object | Pattern Object | Fields / Components To Map |
|---|---|---|
| Save action | Independent selected control | `aria-pressed`, selected class, action label and visible “已选” badge |
| Preference/status actions | Mutually-exclusive controls | More-like, irrelevant and known replace only one another |
| Feedback group | Two-axis state block | Default, hover, submitting, one/two selected and independently cancelled states |

## State Coverage

- Loading: existing HTMX swapping opacity and disabled submit behavior remain.
- Empty: all four actions are neutral and the helper explains when feedback takes effect.
- Error: existing request error path remains unchanged.
- Disabled: submitting button remains temporarily disabled by HTMX.
- Hover: pale primary tint without looking selected.
- Selected: up to two persisted actions use a solid primary surface, white content and “已选” badge: save plus one preference/status action.
- Needs human review: none; no external write or irreversible action is added.

## License And Source Risk

- shadcn dashboard shell: MIT structural reference only; no source component is copied.
- loading/empty/error set: kit-internal state pattern, adapted to existing Jinja/CSS.

## Decision

- Proceed with the two selected patterns.
- Preserve FastAPI, Jinja, HTMX, append-only feedback semantics and the existing color tokens; cancellation only retracts events on the clicked axis.
- Do not introduce a new framework, animation library or brand asset.

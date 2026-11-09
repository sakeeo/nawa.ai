# NAWA.AI Design System

The single visual reference for the NAWA.AI web app (`apps/web`). Every screen, component,
and chart follows this file. When a new pattern is needed, add it here first.

Reference mockup: [`docs/design/dashboard-mockup.html`](design/dashboard-mockup.html) — open it
in a browser; it implements the tokens and components below without any build step.

---

## 1. Principles

1. **Calm and trustworthy.** An enterprise tool used daily. Neutral surfaces, one brand accent,
   no decoration that does not carry information.
2. **Evidence is visible.** AI output always sits next to its proof: citations, the SQL that
   ran, the trace, the model used, the cost. The UI never hides where an answer came from.
3. **State is never color-only.** Status, roles, and providers always combine an icon or text
   label with color.
4. **Self-hosted by construction.** No remote fonts, CDNs, icon services, or analytics. Every
   asset ships with the app, so the UI works fully offline.
5. **Human in control.** Risky actions (send, write, external call) look different: they need
   an explicit confirm step and show who approved them.
6. **Density with breathing room.** Data-heavy screens use compact tables and small type, but
   keep a consistent 4 px spacing rhythm and clear grouping.

## 2. Color tokens

All colors are CSS custom properties on `:root`. Components reference roles, never raw hex.
Dark mode is a selected set of steps, not an automatic inversion.

### 2.1 Brand palette

Source palette (navy → sky):

| Name | Hex | Role |
|---|---|---|
| Navy | `#1B365D` | Sidebar, strong brand, hover/pressed |
| Nawa Blue | `#005A9C` | Primary brand: buttons, links, active state, focus ring (light) |
| Sky | `#60C1E5` | Accent: active indicator, brand in dark mode |
| Ice | `#A0E0EF` | Soft accent: active nav text on navy, brand hover in dark mode |

Brand colors are used for interaction and identity only, never for status.

### 2.2 Neutrals and brand tokens

Neutrals are cool-tinted to sit with the navy/blue brand.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#f4f7fb` | `#0a1524` | Page background |
| `--surface` | `#ffffff` | `#0f1d31` | Cards, tables, header |
| `--surface-2` | `#eef3f8` | `#16263d` | Hover rows, inputs, nested panels |
| `--border` | `#dde5ee` | `#23344d` | Card and table borders, dividers |
| `--text` | `#0e1b2c` | `#e7eef6` | Primary text, values |
| `--text-2` | `#41506a` | `#a9bad0` | Secondary text, labels (8.1:1 / 8.6:1) |
| `--text-3` | `#56657a` | `#8597b0` | Muted text, captions, axis labels (5.9:1 / 5.7:1) |
| `--brand` | `#005a9c` | `#60c1e5` | Primary buttons, links, active tabs, focus ring (7.1:1 / 8.3:1) |
| `--brand-strong` | `#1b365d` | `#a0e0ef` | Hover/pressed brand |
| `--brand-soft` | `#e6f4fa` | `#12304f` | Selected rows, soft badges |
| `--on-brand` | `#ffffff` | `#0b1a2e` | Text on `--brand` |

### 2.3 Navigation (sidebar) tokens

The sidebar is navy in both modes, so the brand reads at a glance.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--nav-bg` | `#1b365d` | `#0b1628` | Sidebar background |
| `--nav-text` | `#d6e2f0` | `#d6e2f0` | Nav item text and icons (9.2:1 on navy) |
| `--nav-muted` | `#8fb0d3` | `#8fb0d3` | Group labels (5.4:1 on navy) |
| `--nav-hover` | `rgb(255 255 255 / 0.08)` | same | Hover background |
| `--nav-active-bg` | `rgb(160 224 239 / 0.16)` | same | Active item background |
| `--nav-active-text` | `#a0e0ef` | `#a0e0ef` | Active item text (8.3:1 on navy) |
| `--nav-indicator` | `#60c1e5` | `#60c1e5` | 3 px active indicator, logo mark, focus ring inside the sidebar |
| `--nav-border` | `rgb(255 255 255 / 0.12)` | `rgb(255 255 255 / 0.08)` | Dividers in the icon-only sidebar |

### 2.4 Status (reserved)

Status colors mean state and are never reused for data series or decoration. Each status
always ships with an icon and a text label.

| Token | Hex (both modes) | Icon | Meaning |
|---|---|---|---|
| `--status-good` | `#0ca30c` | ✓ check | Healthy, ready, approved, passed |
| `--status-warning` | `#fab219` | ! triangle | Degraded, pending, near a limit |
| `--status-serious` | `#ec835a` | ! circle | Needs attention soon |
| `--status-critical` | `#d03b3b` | × cross | Failed, blocked, rejected, down |
| `--status-neutral` | `--text-3` | • dot | Queued, unknown, inactive |

Warning and serious are below 3:1 on the light surface by design: the icon + label carries the
meaning. Text next to a status dot stays in `--text` / `--text-2`.

### 2.5 Data visualization

Charts use a validated categorical palette, assigned **in fixed order, never cycled**. Values
were checked with the dataviz validator against `--surface` in both modes (CVD and
normal-vision separation, contrast ≥ 3:1). Slot 1 takes Nawa Blue in light mode; in dark mode
Sky (`#60c1e5`) is too light for the chart band, so slot 1 uses `#3d9ad1`. Slots 3–8 are the
validated defaults; re-run the validator when combining them with slot 1.

| Slot | Light | Dark | Default meaning in NAWA.AI |
|---|---|---|---|
| `--series-1` | `#005a9c` | `#3d9ad1` | Local model (Ollama / vLLM) |
| `--series-2` | `#eb6834` | `#d95926` | External provider (API) |
| `--series-3` | `#1baf7a` | `#199e70` | Third category |
| `--series-4` | `#eda100` | `#c98500` | Fourth category |
| `--series-5` | `#e87ba4` | `#d55181` | Fifth category |
| `--series-6` | `#008300` | `#008300` | Sixth category |
| `--series-7` | `#6250d6` | `#9085e9` | Seventh category |
| `--series-8` | `#e34948` | `#e66767` | Eighth category |
| `--grid` | `#dde5ee` | `#23344d` | Gridlines, baselines |

Rules:

- Color follows the entity, not its rank: "Local" is always slot 1, "External" always slot 2.
- More than 8 series fold into "Other" or small multiples. Scatter and maps use at most 3 slots.
- Sequential (magnitude): one hue, light → dark, from the blue ramp
  (`#cde2fb` → `#0d366b`). Diverging: blue ↔ red with a gray midpoint
  (`#f0efec` light / `#383835` dark).
- Before adding a new categorical combination, run the validator on it in both modes.

## 3. Typography

System font stack only (no downloaded fonts):

```css
--font-sans: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue",
  Arial, "Noto Sans", sans-serif;
--font-mono: ui-monospace, SFMono-Regular, "Cascadia Code", Menlo, Consolas, monospace;
```

| Token | Size / line height | Weight | Use |
|---|---|---|---|
| `--text-xs` | 12 / 16 px | 400–500 | Captions, axis labels, badges |
| `--text-sm` | 14 / 20 px | 400–500 | Body default, tables, inputs |
| `--text-md` | 16 / 24 px | 500–600 | Card titles, chat messages |
| `--text-lg` | 20 / 28 px | 600 | Page titles |
| `--text-xl` | 28 / 36 px | 600 | Stat tile values |

- Numbers in tables and stat tiles use `font-variant-numeric: tabular-nums`.
- SQL, model names, IDs, and tokens use `--font-mono` at `--text-xs`/`--text-sm`.
- Sentence case everywhere ("Pending approvals", not "Pending Approvals").

## 4. Space, shape, elevation

| Token | Value |
|---|---|
| Spacing scale | 4 px base: 4, 8, 12, 16, 20, 24, 32, 40, 48 |
| `--radius-sm` | 6 px — badges, inputs, small buttons |
| `--radius-md` | 10 px — cards, menus, dialogs |
| `--radius-full` | 999 px — pills, avatars, status dots |
| `--shadow-1` | `0 1px 2px rgb(16 24 40 / 0.06)` — cards (light only) |
| `--shadow-2` | `0 8px 24px rgb(16 24 40 / 0.12)` — menus, dialogs, tooltips |
| Focus ring | `2px solid var(--brand)` + `2px` offset, on every interactive element |

In dark mode, elevation comes from `--surface` vs `--bg` contrast and borders; shadows are
reduced.

## 5. Layout

The app uses the full screen width. Content is fluid up to 2200 px, then centered.

```text
┌──────────┬───────────────────────────────────────────────────────────────┐
│          │ Header (56 px): menu (phone) · workspace switcher · search ·  │
│ Sidebar  │ provider badge · offline badge · theme · user menu             │
│ navy     ├───────────────────────────────────────────────────────────────┤
│ 240 px   │ Page title + actions                                           │
│          │ Content: fluid, 12-column grid, gutters 16 px (20 px ≥ 1600)   │
└──────────┴───────────────────────────────────────────────────────────────┘
```

| Breakpoint | Sidebar | Content padding | Dashboard placement (12 columns) |
|---|---|---|---|
| ≥ 2200 px | 240 px | 32 px, canvas centered at 2200 px | Same as ≥ 1600 |
| 1600–2199 px | 240 px | 24 / 32 px | Stats 4 × 3 · calls 6, cost 3, health 3 · approvals 6, activity 6 (approval actions inline on the right) |
| 1280–1599 px | 240 px | 24 px | Stats 4 × 3 · calls 8, cost 4 · approvals 4, activity 4, health 4 |
| 1024–1279 px | 64 px icons (labels as tooltips) | 24 px | Same as 1280–1599 |
| 768–1023 px | 64 px icons | 24 px | Stats 2 × 6 · calls 12 · cost 6, health 6 · approvals 6, activity 6 |
| < 768 px | Drawer (menu button, backdrop, Esc closes) | 16 px | Stats 2 × 6 · every panel 12 |

- Place cards with grid spans and `order`, not by duplicating markup per breakpoint.
- Charts re-render on resize and space axis labels at least 56 px apart.
- Navigation follows the product structure. Items appear only when their phase ships:

| Group | Items | Phase |
|---|---|---|
| — | Overview, AI Assistant | 1 |
| Knowledge | Knowledge bases, Documents | 1 |
| Data | Data sources, Schema explorer, Semantic layer | 2 |
| Agents | Agents & tools, Runs | 3 |
| Workflows | Workflows, Run history | 4 |
| — | Approvals | 3–4 |
| Monitoring | Usage & cost, Evaluations, Audit log | 0+ |
| Settings | Workspace & members, AI providers, Integrations | 0 |

## 6. Components

Each component lists its anatomy and states. All interactive components have hover, focus,
active, and disabled states.

### 6.1 App shell

- **Sidebar:** navy (`--nav-bg`). Logo, nav groups with 11 px uppercase group labels in
  `--nav-muted`, items 36 px tall with icon + label in `--nav-text`. Active item:
  `--nav-active-bg` background, `--nav-active-text` text and a 3 px `--nav-indicator` left
  bar. Icon-only mode shows a divider instead of group labels.
- **Header:** workspace switcher (current workspace + role badge), global search, then right
  side: provider badge, offline badge (only when offline), theme toggle, user menu.

### 6.2 Buttons

| Variant | Look | Use |
|---|---|---|
| Primary | `--brand` fill, `--on-brand` text | One main action per view |
| Secondary | `--surface` fill, `--border` border | Other actions |
| Ghost | No border, `--text-2` | Toolbar and inline actions |
| Danger | `--status-critical` fill, white text | Destructive or risky actions; always behind a confirm |

Height 36 px (32 px compact), radius `--radius-sm`, 14 px medium label, optional 16 px icon.

### 6.3 Inputs

36 px height, `--surface` background, `--border` border, `--radius-sm`. Label above (14 px,
`--text-2`), help or error text below (12 px). Error state: `--status-critical` border plus an
error message; never color alone.

### 6.4 Cards and panels

`--surface`, 1 px `--border`, `--radius-md`, `--shadow-1`, 20 px padding. Header row: title
(16 px semibold) + optional caption (12 px `--text-3`) + optional action on the right.

### 6.5 Stat tile

Label (12 px `--text-2`), value (28 px semibold, tabular), delta line (12 px): arrow icon +
signed change + comparison period, in `--text-2`. The arrow shape carries direction; color is
not used for good/bad because "up" is not always good (cost, latency).

### 6.6 Tables

Header row 36 px, 12 px medium `--text-3`, sticky. Body rows 44 px (36 px compact), 14 px,
1 px `--border` row dividers, `--surface-2` on hover. Numbers right-aligned and tabular.
Empty state inside the table body.

### 6.7 Badges

Pill, 20 px tall, 12 px medium, `--radius-full`.

| Badge | Content |
|---|---|
| Status | Colored icon + label, neutral background (`--surface-2`) |
| Role | `admin` / `manager` / `member` / `viewer` in `--surface-2` with `--text-2` |
| Provider | **Local** (series-1 dot + "Local · qwen2.5:7b") or **External** (series-2 dot + "External · deepseek-chat") |
| Offline | Shield icon + "Offline mode" in `--brand-soft` / `--brand` |

### 6.8 AI evidence components

- **Citation chip:** `[1]` superscript-style chip in `--brand-soft`; hover shows document name,
  page, and snippet; click opens the chunk.
- **SQL block:** monospace, `--surface-2`, copy button, "Read-only · LIMIT 1000" caption.
- **Trace link:** "View trace" ghost button with model, tokens, latency, and cost in a caption.
- **Refusal:** neutral panel with an info icon: "Not found in the documents."

### 6.9 Approval item

Action summary, target, requester, time, risk badge (status warning), and two buttons:
**Approve** (primary) and **Reject** (secondary). After a decision the item shows who decided
and when.

### 6.10 Feedback states

- **Loading:** skeleton blocks in `--surface-2`; no spinners longer than 1 s without text.
- **Empty:** short sentence + one action ("No documents yet. Upload a file.").
- **Error:** problem title + detail from the API (RFC 7807) + a retry action.
- **Toast:** bottom-right, `--surface`, `--shadow-2`, status icon, auto-dismiss 5 s (errors stay).

## 7. Charts

Follow the dataviz method; these are the NAWA.AI defaults.

- **Form first:** a single headline number is a stat tile, not a chart; change over time is a
  line; comparison across categories is a bar.
- **One y-axis only.** Two measures with different units (calls and cost) are two charts.
- **Marks:** 2 px lines, bars with a 4 px rounded data end and 2 px gaps, markers ≥ 8 px on
  hover only.
- **Labels:** a legend for ≥ 2 series plus direct end-labels for ≤ 4 series. Never a number on
  every point. Text uses text tokens, never the series color.
- **Axes and grid:** recessive (`--grid`, 12 px `--text-3` labels), baseline at zero for bars.
- **Hover by default:** crosshair + tooltip on lines, per-bar tooltip on bars; hit targets
  larger than the mark.
- **Table view:** every chart offers "View as table".
- **Library:** ECharts (Phase 2+) configured with these tokens; small dashboard charts may be
  inline SVG.

## 8. Accessibility

- WCAG 2.2 AA: text contrast ≥ 4.5:1 (all text tokens pass on `--surface` and `--bg`),
  UI component contrast ≥ 3:1.
- Every interactive element is reachable by keyboard and shows the focus ring.
- Icons that carry meaning have an accessible name; decorative icons are `aria-hidden`.
- Respect `prefers-reduced-motion` (no animated transitions) and `prefers-color-scheme`; the
  theme toggle overrides both ways.
- Charts have a text summary (`aria-label`) and a table view.

## 9. Voice and copy

- UI copy in English for now; content (documents, demo data, questions) may be Indonesian.
  Bahasa Indonesia UI arrives with i18n.
- Short, concrete, sentence case. Name the thing: "Invite member", not "Submit".
- Say what happened and what to do next in errors: "Setup has already been completed. Sign in
  instead."
- Never claim certainty the system does not have. AI answers show sources or say they were not
  found.

## 10. Implementation in `apps/web`

- Tokens live in `src/app/globals.css` as CSS variables under `:root` and `[data-theme="dark"]`
  (plus a `prefers-color-scheme` fallback), copied from section 2.
- Tailwind maps the tokens (`bg-surface`, `text-text-2`, `border-border`, `bg-brand`, …) via
  the theme configuration so components never use raw hex.
- Icons: an icon set bundled with the app (for example `lucide-react`); never an icon CDN.
- Component primitives (shadcn/ui or equivalent) must be restyled to these tokens.
- New components are added to this document, then to the mockup if they change the dashboard.

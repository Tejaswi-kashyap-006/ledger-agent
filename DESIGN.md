# Ledger Agent: design direction

> **Status: APPROVED (2026-09-28).** Every token, font weight and spacing rule here is binding for all UI
> work (see [`docs/UI_DESIGN_PROTOCOL.md`](docs/UI_DESIGN_PROTOCOL.md)). To change the system, change this file first, then the code.
> Implementation: `ui/src/styles/tokens.css` mirrors the tables below one to one.

## Direction: "The Red Khata"

The *bahi-khata* is the red cloth-bound account book Indian traders have kept for generations: a crimson
spine, cotton paper with ruled columns, a red double margin line, entries in black ink, notes pencilled
in the margin, and rubber stamps when something is settled. Ledger Agent does that same job, so the
interface **is** that book, re-set with the rigor of a Swiss financial table.

**Philosophy: tactile ledger precision.** One saturated color used boldly (the crimson binding) against a
warm paper field. Every text line sits on a ruled line. Numbers set like a typewriter. Ornament only
where a real account book has it: the spine, the margin rule, the stamp, the pencil.

The visual system also **encodes trust**, which is what this app is really about (see `docs/THEORY.md` §1):

| Who decided | How it looks | Why |
|---|---|---|
| The model (a suggestion) | **blue pencil**, handwritten face, in the margin | provisional, erasable, not yet in the books |
| A rule (deterministic) | black ink + a small **RULE** stamp | committed by a mechanism you can inspect |
| You (verified) | solid **black ink**, initialled with a tick | the ground truth |
| Needs attention | **haldi** (turmeric) highlighter swipe behind the entry | a person should look at this |
| Settled | green **RECONCILED** stamp, rotated -4° | balances checked out to the paisa |

## Typography

| Role | Face | Why this face | Usage |
|---|---|---|---|
| Display | **Rozha One** (Indian Type Foundry) | high-contrast, heavy, Indian-designed, Latin + Devanagari | page titles, the hero figure, the spine wordmark |
| Body / UI | **Mukta** (Ek Type) 400 / 500 / 700 | humanist, calm at small sizes, Latin + Devanagari | all interface text, labels, prose |
| Figures | **IBM Plex Mono** 400 / 500 | typewriter ledger feel, fixed-width figures align in columns | every amount, date and count in tables |
| Marginalia | **Kalam** 400 (ITF handwriting) | reads as pencil | *only* model suggestions and reasons, ≥ 17px, never more than 2 lines |

Self-hosted through Fontsource, so no request to Google Fonts from a finance app. **Ship the `latin-ext`
subsets**: that's where all four faces keep the ₹ glyph (verified with fontTools; the plain `latin` subsets
don't contain it).

**Scale** (perfect fourth, 1.333, base 16px):

| token | px | use |
|---|---|---|
| `--t-xs` | 12 | stamp text, table kickers (mono, uppercase, +0.12em tracking) |
| `--t-sm` | 14 | table body figures, metadata |
| `--t-md` | 16 | body |
| `--t-lg` | 21 | section heads (Mukta 700) |
| `--t-xl` | 28 | page subtitles, card figures |
| `--t-2xl` | 38 | page titles (Rozha) |
| `--t-3xl` | 50 | |
| `--t-hero` | 90 | the one hero figure per view (Rozha) |

Deliberate deviation from the data-viz default ("hero figures in the system sans"): this direction sets the
hero figure in Rozha One, the ledger's display face. Chart axes, ticks and tooltips stay in Mukta/Plex Mono.

## Color

All colors are CSS variables on `:root`. The dark theme ("lamplit khata") is re-stepped, not inverted.
Theme switching follows the course docs' convention: `prefers-color-scheme`, overridden by `data-theme`.

| token | light | dark | role |
|---|---|---|---|
| `--paper` | `#F3EBDA` | `#1C1814` | page field (with grain) |
| `--paper-deep` | `#E8DCC4` | `#15120F` | the sheet peeking behind the page, sunk areas, inactive tabs |
| `--card` | `#FBF6EA` | `#26201A` | index cards and receipts laid *on* the page |
| `--rule` | `#D9CBB0` | `#2E2822` | ruled lines, hairlines |
| `--ink` | `#1C1A17` | `#EDE3CF` | primary text (14.6:1 / 13.9:1) |
| `--ink-2` | `#4A443B` | `#C9BDA8` | secondary text (8.1:1) |
| `--muted` | `#6B6254` | `#A39785` | kickers, axis text (≥ 4.5:1 / 6.2:1) |
| `--khata` | `#7A1719` | `#5E1214` | **dominant**: the spine, primary actions, active tab |
| `--khata-ink` | `#8C1C1F` | `#EC7D72` | crimson text, the margin rule, critical (7.7:1 / 6.5:1) |
| `--pencil` | `#1F4E8C` | `#8FB2EA` | model suggestions (7.0:1 / 8.2:1) |
| `--haldi` | `#E9B949` | `#E9B949` | attention highlighter (ink on haldi 9.5:1) |
| `--cleared` | `#2D6A3E` | `#6FBF84` | reconciled / verified stamps (5.5:1 / 8.0:1) |
| `--on-khata` | `#F3EBDA` | `#F3EBDA` | text on the spine (9.0:1 / 11.3:1) |
| `--on-haldi` | `#1C1A17` | `#1C1A17` | text on the haldi highlighter, in both themes (9.5:1) |

**Chart series** (validated with `dataviz/scripts/validate_palette.js`, all checks pass):

| slot | light (on `#F3EBDA`) | dark (on `#1C1814`) | meaning |
|---|---|---|---|
| 1 | `#9B2226` crimson | `#E0645A` | money out |
| 2 | `#2A5C9E` ink blue | `#6593D8` | money in |

CVD worst-pair ΔE 19.7 (light) / 18.6 (dark), normal vision 25.0 / 24.6, all ≥ 3:1 on paper. Single-series
charts (spend by category) use slot 1 only. Status colors (`--cleared`, `--haldi`, `--khata-ink`) are never
used as series colors and always come with an icon and a label.

## Space & layout

**Everything sits on the ruled line.** The base line is 28px (the body line height). Horizontal spacing uses
multiples of 7px (`7 · 14 · 21 · 28 · 42 · 56 · 84 · 112`). **Vertical** spacing in the text flow uses whole
lines only (28 · 56 · 84 · 112).

### The baseline grid (how "sits on the line" is enforced)

Added 2026-09-29 after the first build showed rules running through text. These rules are binding:

| Rule | Why |
|---|---|
| The page rule is drawn at `--rule-y` = **20px** inside each 28px band | Mukta 16px sits at 18px in a 28px line box (measured), so text rests 2px above its rule instead of floating |
| Every line box is 28px, or 56 / 112 for display type | anything else drifts off the ruling |
| Display faces get a measured `top` nudge (layout untouched): title +7px, hero −9px, section heads and 21px text −2px, figure-face table cells −2px, Jama/Naam figures +10px, stat line +4px | their baselines don't land where Mukta's does |
| **Inline runs in another face** (figures, pencil, small print, stamps) get `line-height: 1` | a 28px inline box with a lower baseline stretches the line to 30px and pushes every later line off the grid |
| Blockified spans (grid or flex items) get their full 28px line back | otherwise they collapse |
| No layout-affecting borders in the flow. Heavy rules are drawn **on** the ruled line (gradient at `--rule-y`), and tables have no row borders: the page's rules are the row rules | a 1–2px border shifts everything after it |
| Variable-height blocks (cards, receipts, charts, tables) are snapped by `ui/src/lib/rhythm.ts`: each flow child gets a bottom margin that rounds it up to whole lines | the next block starts on the grid, whatever the data |
| Display type that spans several rules (page titles, the hero figure, big stats) is set on a clean patch of paper; the one-line kicker only lifts the red margin rule | rules through a 90px numeral read as a strikethrough |
| A hanging title unit (kicker + title) shares one left edge; the intro paragraph returns to the text column | the kicker and title read as one object crossing the margin |
| Wide tables restack each row into a 3-line block when **their own column** is narrow (CSS container queries on `.table-scroll`, not viewport breakpoints). One-line cells in a restacked row never wrap (ellipsis) | at 1280px the margin column squeezes the text column; a wrapped cell would spread an extra line over two grid rows (14px each) |

**Verification:** `ui/scripts/check-rhythm.mjs` measures every text line's real baseline in Chrome and fails if any is
off its rule or crossed by one. It also flags content hidden inside a scroll box. It must report 0 problems at 1440, 1280, 1024, 800, 390 and 360px before UI changes ship.

```
┌────┬─╥──────────────────────────────────────────────────────┬──────────────────┐
│ S  │T║  SEPTEMBER FOLIO                                     │  marginalia      │
│ P  │A║ ─────────────────────────────────────────────────────│  (trend chart,   │
│ I  │B║  ₹ 42,318 ← hero crosses the red margin rule         │   stamps, notes) │
│ N  │S║  ─ ruled rows: jama · naam ──────────────────────────│                  │
│ E  │ ║                                                      │                  │
└────┴─╨──────────────────────────────────────────────────────┴──────────────────┘
 72px  index   main column (≤ 728px), left-aligned, not centered   280px margin column
       tabs    ║ = red double margin rule, 84px into the sheet
```

- **Spine** (72px, fixed): crimson cloth with a fine diagonal weave, the wordmark `बही-खाता · LEDGER` set
  vertically in Rozha One, and the theme toggle at the foot.
- **Index tabs**: navigation as paper tabs cut into the page's left edge, like a ledger's alphabet index.
  The active tab is the same paper as the page and merges into it; inactive tabs sit one step darker.
  Labels are plain English (Review, Ledger, Reports…). The evocative words go in page headings.
- **The sheet**: left-aligned, not centered. It has a second sheet peeking 7px behind it (the only drop
  shadow in the app). The **red double margin rule** runs top to bottom 84px in, and each title unit (kicker +
  title) and the hero unit (label + figure) **start left of it and cross it**, which is the grid-breaking gesture.
  Where their ink crosses the red rule, the rule steps aside.
- **Margin column** (280px, right): charts, stamps and notes live here like marginalia, never in a row of
  equal cards. Below 1100px it folds under the main column. Below 720px the tabs become a bottom bar and
  the spine becomes a 7px crimson top edge.

## Depth

- **Paper grain**: an inline SVG `feTurbulence` noise at ~6% opacity over `--paper`, plus ruled lines as a
  `repeating-linear-gradient` every 28px at the `--rule` color.
- **Cloth weave** on the spine: two crossed hairline `repeating-linear-gradient`s, tone-on-tone.
- **Layered sheets**: page, sheet behind, and the receipt and index cards sit *on* the page with a hairline
  and a 2px offset shadow. No blurred glows, no uniform card shadows.
- **Stamps**: bordered uppercase mono text, rotated −4° to −7°, multiply blend, slightly uneven ink (SVG mask).

## Motion: one orchestrated moment per view, then stillness

Page load, about 900ms total:

| t | what happens |
|---|---|
| 0ms | spine slides in from the left (120ms) |
| 80ms | ruled lines draw left to right (`scaleX` 0 → 1, 360ms, ease-out) |
| 240ms | the red margin rule drops top to bottom (280ms) |
| 380ms | title and hero figure **ink in**: opacity 0 → 1 with a 2px blur settling to sharp (260ms) |
| 480ms + 40ms × n | ledger rows appear one by one, up to 12 rows (later rows appear at once) |

**The signature interaction is the stamp.** Accepting a review item presses a stamp onto the entry (scale
1.35 → 1, rotation settles, 160ms, a slight ink-bleed shadow), then the entry slides into the "posted"
pile. No hover wobbles or bouncing buttons anywhere else. `prefers-reduced-motion`: everything appears
instantly, and the stamp becomes a simple fade.

## Pages and their real copy

| Route | Heading | What it holds |
|---|---|---|
| `/` | **{Month} folio** (e.g. "September folio") | the hero figure *Net this month*; two ruled columns **Jama · money in** and **Naam · money out**; spend by category as ruled rows with inline bars; in the margin, the in-vs-out trend and a haldi note "13 entries await your initials" |
| `/import` | **Post a statement** | a drop slot styled as a letterbox; each result comes back as a printed receipt (mono, torn edge) with rows new, duplicate and rejected, and a RECONCILED or BALANCE MISMATCH stamp |
| `/review` | **Entries awaiting your initials** | one entry at a time, large, as an index card: narration, amount, and the model's pencilled suggestion with its reason. Keys: `Enter` accepts, `1`–`9` picks a suggested category, `/` searches categories, `S` skips. A counter shows how many are left and what a rule just auto-fixed ("rule compiled · 2 more fixed") |
| `/audit` | **Spot-check the confident ones** | the same card, with copy explaining why audits exist ("the model was sure; mistakes it's sure about never reach Review") |
| `/ledger` | **The ledger** | the full ruled table: date, narration, merchant, category (pencil, ink or RULE stamp), account, amount; search and filters in one row above; paginated by folio (month) |
| `/ask` | **Ask the munim** | a conversation set like correspondence; each answer carries footnote-style marginalia listing the tools it consulted ("consulted: spending_summary · 1–31 Jul") |
| `/reports` | **Monthly folio** | an editorial single column; numbers verified against the books get a small tick, and sentences the verifier removed appear at the end under **Struck from the record** with a strikethrough |
| `/subscriptions` | **Standing charges** | recurring payments; price rises marked in `--khata-ink` with an arrow **and** "+23.1%" (never color alone) |
| `/settings` | **Rules, memory & keys** | the household, preferences and goals memory blocks as editable paper slips; rules as a ruled list; the API bearer token |

## Component inventory (built once, reused everywhere)

The repo has no app components yet. The course `docs/` site is a separate surface with its own style and
no forms or data tables, so nothing carries over except the `data-theme` convention. The UI will build
exactly these, in `ui/src/components/`:

`Spine` · `IndexTabs` · `Sheet` (ruled page + margin rule + margin column) · `Folio heading` ·
`HeroFigure` · `Amount` (Plex Mono, ₹, Indian grouping, explicit − sign) · `Pencil` (model text) ·
`Stamp` (RECONCILED / RULE / VERIFIED / SUSPICIOUS / MISMATCH, each with an icon) · `Highlight` (haldi) ·
`RuledTable` · `EntryCard` (review/audit) · `CategoryPicker` (combobox, keyboard-first) ·
`Receipt` (import result) · `Button` (`ink` primary on khata, `quiet` secondary, `stamp` for commit
actions) · `Field` (text inputs sitting on a rule line, no boxes) · `Toast` (a slip of paper) ·
charts: `RuledBars`, `InOutTrend` (validated palette, tooltip, legend, table view).

## Charts

- **Spend by category**: horizontal bars **inside ruled table rows**, one series (slot 1), ≤ 24px thick,
  4px rounded end, value at the bar tip in Plex Mono, tooltip on hover and focus.
- **In vs out by month**: two 2px lines (slot 1 = money out, slot 2 = money in), end dots ≥ 8px with a 2px
  paper ring, a legend plus direct end labels, crosshair tooltip listing both series, and a "Show as table" toggle.
- One y-axis always. Gridlines are the page's own ruled lines, so no extra chart chrome is drawn.

## Explicitly not doing

No centered three-card rows. No gradients on white. No glassmorphism. No uniform soft shadows. No emoji
icons. No Inter, Roboto or Space Grotesk. No decorative motion beyond the load sequence and the stamp.

# Ledger Agent: web UI

React 19 + TypeScript + Vite. The design system is **"The Red Khata"**: the app is laid out like a
*bahi-khata*, the red cloth-bound account book. Before touching a stylesheet, read:

1. [`../docs/UI_DESIGN_PROTOCOL.md`](../docs/UI_DESIGN_PROTOCOL.md): the rules for all UI work in this repository
2. [`../DESIGN.md`](../DESIGN.md) (**Approved**): tokens, type, layout, motion, page copy. It's binding.

## Run it

```powershell
# terminal 1 - the API (any database; the demo seed needs no API key)
cd ledger-agent
python scripts/seed_demo_db.py data/demo.db       # optional: realistic sample ledger
$env:LEDGER_DB_PATH = "data/demo.db"; ledger serve  # :8000

# terminal 2 - the UI with hot reload, proxying /v1 to :8000
cd ledger-agent/ui
npm install
npm run dev                                        # http://localhost:5173
```

Production: `npm run build` writes the app **into the Python package** (`src/ledger_agent/static/`).
Then `ledger serve` serves the UI and the API on one port, and `pip install` / the Docker image ship it.

| Script | Does |
|---|---|
| `npm run dev` | Vite dev server with API proxy (`LEDGER_API=http://host:port` to point elsewhere) |
| `npm run typecheck` | `tsc` in strict mode with `noUncheckedIndexedAccess` |
| `npm test` | Vitest + Testing Library (jsdom) |
| `npm run build` | typecheck, then build into `../src/ledger_agent/static` |
| `npm run check:rhythm -- <width>` | measures every text baseline against the ruling in real Chrome (see below) |

## Layout of the code

```
src/
  main.tsx              fonts (self-hosted), styles, theme, router
  App.tsx               the book: spine + index tabs + routes; live review count
  lib/
    api.ts              typed client for every endpoint; ApiError; bearer token in localStorage
    types.ts            response shapes (mirror src/ledger_agent/api.py)
    format.ts           ₹ + Indian grouping, true minus sign, lakh/crore compacts, dates, reason copy
    richText.tsx        SAFE renderer for model answers (no innerHTML: narrations are attacker-controlled)
    hooks.ts            useAsync (stale-safe), useStoredState
    rhythm.ts           keeps every block on the 28px ruling (snaps variable-height blocks to whole lines)
    theme.ts            system / day / lamplit, via data-theme (same convention as the course docs)
    categories.ts       quick-pick shortcuts for the review card
  components/           the inventory listed in DESIGN.md - reuse before you build
    Book.tsx            Spine, IndexTabs, Sheet (ruled page + margin rule + marginalia), FolioHead, Section
    Ledger.tsx          Amount, Stamp, Pencil, Highlight, CategoryLabel, HeroFigure
    Controls.tsx        Button (ink/quiet/stamp), TextField, SelectField, TextArea, Loading, ErrorNote
    CategoryPicker.tsx  keyboard-first ARIA combobox
    EntryCard.tsx       the review/audit index card
    Receipt.tsx         import result with a torn edge
    Toast.tsx           the "slip" confirmation (polite live region)
    charts/             RuledBars (one series), InOutTrend (two series, validated palette)
  pages/                one file per route
  styles/
    tokens.css          every color, font, size, space and easing, mirroring DESIGN.md
    base.css            paper grain, type roles, focus, reduced-motion contract
    layout.css          book grid, spine, tabs, sheet, margin rule, load sequence, responsive
    components.css      the components above
    pages.css           page compositions
```

## Rules that the code enforces (don't break them)

- **Text sits on the ruled line.** Read DESIGN.md → "The baseline grid" before changing any line height, margin,
  padding or border in the text flow. After any UI change, run the rhythm checker (it must print 0 problems at
  1440, 1280, 1024, 800, 390 and 360px):
  ```
  # with `ledger serve --port 8765` running and Chrome started with --remote-debugging-port=9333
  npm run check:rhythm -- 1440
  ```
  New flow containers go in **both** `FLOW_CONTAINERS` (`lib/rhythm.ts`) and the flow rule in `styles/layout.css`.

- **Colors, fonts and spacing only through tokens.** No hex values outside `tokens.css`. Spacing is a multiple of 7px, and the line is 28px.
- **Trust is visible.** Model output is blue pencil (`Pencil`, `.cat--pencil`). Rules get a RULE stamp. Your decisions are ink plus "You".
  Text on the haldi highlighter always uses `--on-haldi`.
- **Chart colors are validated**, not chosen by eye (`--series-in` / `--series-out` passed the dataviz validator in both themes).
  One y-axis, a legend plus direct labels, a tooltip on hover *and* keyboard, and a table view.
- **Motion**: one load sequence per page (`.ink-in`, `.stagger`) and the stamp. Nothing else animates.
  `prefers-reduced-motion` turns it all off (see `base.css`).
- **Large text blocks are never rotated** (it blurs glyphs). Rotation is only for stamps and slips.
- **No layout may widen the page.** `.sheet` clips horizontal overflow, and tooltips grow inward.
- **Model text is rendered with `RichText`**, never `dangerouslySetInnerHTML`.

## How it was verified

- `npm run typecheck`, `npm test` (formatting, safe rendering, API client, combobox keyboard flow, charts,
  keyboard review flow including suspicious entries and sibling flags)
- A DevTools-protocol smoke test against a real `ledger serve`: every route loads with zero console errors;
  pressing Enter on Review posts an entry and the server's backlog drops. `/` then typing then Enter posts
  under a searched category.
- Screenshots in both themes at 1440px and at true 390px device emulation (no horizontal overflow on any page).
  See `../docs/images/`.

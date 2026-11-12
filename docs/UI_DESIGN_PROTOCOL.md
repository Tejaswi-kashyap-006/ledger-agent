# UI Design Protocol

Binding instructions for **all UI work in this repository**. Read it before touching a stylesheet.

## 1. Core methodology & the "anti-slop" protocol

Act as an expert UI/UX designer and frontend engineer. The primary goal is to produce distinctive,
production-grade interfaces that strictly avoid generic "AI slop" aesthetics.

- **Banned defaults.** Never use generic fonts (Arial, Inter, Roboto, Lato, Open Sans) or fonts overused
  by AI (Space Grotesk). Never use timid, evenly distributed pastel palettes. Strictly avoid
  purple/indigo gradients on white backgrounds.
- **Banned layouts.** Do not use the standard "SaaS card kit" layout (three identical rounded cards
  centered symmetrically).
- **Banned descriptors.** Do not aim for "modern and clean" or "user-friendly". These trigger generic
  statistical averages.

## 2. Evocative, principle-based design

Before writing any UI code, define a strict, evocative aesthetic direction and commit to it unconditionally.

- Choose a bold conceptual philosophy (e.g. "editorial brutality", "maximalist chaos", "refined
  minimalism", or Japanese *wabi-sabi* emphasizing negative space and impermanence).
- Match implementation complexity to the vision: maximalism needs elaborate CSS animation and depth;
  minimalism needs absolute restraint and a flawless spacing grid.

## 3. The five pillars of aesthetic quality

1. **Typography.** Pair a distinctive, characterful display font with a highly refined body font (e.g.
   Playfair Display for editorial, JetBrains Mono for technical). Establish a strict typographic scale.
2. **Color.** A dominant color paired with sharp, deliberate accents. Implement **all** colors as CSS
   variables for theming.
3. **Spatial layout.** Prefer unexpected layouts: asymmetry, diagonal flows, overlapping elements,
   grid-breaking typography. Use generous, deliberate negative space.
4. **Visual depth.** Avoid flat backgrounds. Build atmosphere with noise textures, layered
   transparencies, geometric patterns or gradient meshes. Do not apply identical soft drop shadows to
   every container.
5. **Motion design.** Avoid scattered micro-interactions. Create high-impact moments, such as one
   well-orchestrated page-load sequence using staggered CSS `animation-delay`.

## 4. Execution workflow & persistent memory

1. **Context check.** Before starting, read [`DESIGN.md`](../DESIGN.md). If it exists, obey its established tokens, font weights and spacing
   rules unconditionally, to prevent drift between pages and sessions.
2. **Component inventory.** Inventory the existing components before building new ones. Don't reinvent
   buttons or inputs that already exist.
3. **Real content.** Use real, contextually specific copy. Never "Lorem ipsum" or placeholders like
   "Feature One".
4. **Wait for approval.** Outline the chosen direction, typography and color plan. **Stop and wait for
   human confirmation before writing HTML/CSS or React code.** Once approved, record the direction in the
   product's `DESIGN.md` as the source of truth.

## Why this file exists

It's a fixed methodological anchor. The bans rule out generic defaults and symmetric card layouts, which
forces distinctive typography and asymmetric composition. The mandatory evocative direction replaces a
list of pixel values with a philosophy. The inventory step plus `DESIGN.md` keep a multi-page app visually
consistent across sessions.

## How this combines with other rules

- **Charts** still follow the data-viz method: palettes validated with the validator script (never
  eyeballed), one y-axis, a legend for ≥ 2 series, hover tooltips plus a table view, and status colors
  never used as series colors. The aesthetic direction chooses the hues. The validator decides whether
  they ship.
- **Accessibility is not optional styling.** Body text ≥ 4.5:1 contrast, visible focus, keyboard paths
  for every action, and `prefers-reduced-motion` honored by every animation.

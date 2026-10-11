# Design Style Guide — AutoLab

## Aesthetic Direction

**Instrument panel for a robotics lab.** Dark, quiet, technical. The dashboard is
evidence, not decoration: judges and teammates should read state at a glance
and trust where every number came from. A faint 32 px graph-paper grid sits
behind everything (a nod to the calibration board). Motion is minimal and
functional: short fades, staggered reveals on load, a pulsing dot for "live".

The one hard rule: **measured, simulated and replayed data never share a
color.** Every plot point, table row and metric block carries its provenance.

## Color Palette (`src/client/index.css` `@theme`)

| Token | Value | Use |
|---|---|---|
| `lab-bg` | `#0a0d0e` | page background |
| `lab-panel` | `#10161a` | panels / cards |
| `lab-raised` | `#161f23` | hover rows, inset blocks |
| `lab-line` | `#213030` | borders, dividers |
| `lab-grid` | `#172120` | background grid |
| `lab-text` | `#dbe5e1` | primary text |
| `lab-dim` | `#8a9a96` | secondary text |
| `lab-faint` | `#56665f` | captions, axis labels |
| `measured` | `#5ad1b8` | camera-measured, real hardware |
| `simulated` | `#b59cf5` | twin / simulation / mock arm |
| `replay` | `#8fb4e8` | replayed historical data |
| `target` | `#ece6d2` | requested target markers |
| `ok` / `warn` / `fail` | `#6cd38f` / `#e6b450` / `#f0705f` | restrained status |

The scaffold's Tailwind `gray/white/black/blue/red` palettes are **remapped**
to an inverted lab scale (e.g. `white` → panel, `gray-900` → primary text,
`blue-600` → teal accent, `red-600` → fail coral). Starter components and the
auth pages inherit the theme without being forked. Prefer the `lab-*` and
semantic tokens in new code.

## Typography

Google Fonts, imported at the top of `index.css`:

- **Space Grotesk** (`font-display`): headings, panel titles, big numbers.
- **IBM Plex Sans** (`font-sans`): body text.
- **JetBrains Mono** (`font-mono`): IDs, coordinates, metrics, diffs, and every
  number with units. Use `.tabular` for aligned numeric columns.

Panel titles are small uppercase mono labels with wide tracking; values are large.

## Spacing & Radius

- 4 px base unit; panels use `p-4`, page gutter `px-4 md:px-6`, grid gaps `gap-3`/`gap-4`.
- `--radius-panel: 10px` for panels, `--radius-chip: 6px` for chips/badges.
- Borders are 1 px `lab-line`; no drop shadows except focus rings.

## Animation Utilities

- `animate-fade-in` (280 ms) for content swaps.
- `animate-slide-up` (360 ms) for entering rows/panels; wrap children in
  `.stagger` and set `style={{'--i': n}}` for staggered reveals.
- `animate-pulse-dot` for live-status indicators only.
- `animate-scan` for the thin progress sweep on running campaigns.

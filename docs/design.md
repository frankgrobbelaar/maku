# Design

How Maku looks and behaves. Maku keeps its sibling Kura's shapes, type and motion (Kura calls its
look Cinema) in colours of its own: **four schemes**, each in light and dark, picked in Settings ›
General. The [Maku Design canvas](https://claude.ai/artifact/1pVuwSLdjXnp4gPJygp8B8) holds the
owner's picks on two boards, Names and Colour schemes (every scheme in dark and light); snapshots
you can open locally are in [design/](design/index.html). Every screen's layout comes from Kura's
boards, in the [Kura Workflows canvas](https://claude.ai/artifact/XgGkfpW6doBUPcnrPqrbxb) and
those after it (Kura's [docs/design/](https://github.com/frankgrobbelaar/kura/tree/main/docs/design)
has them as pages). Build to those, in Maku's words and colours, and never change the look
unasked.

## The bar

Simple to use and beautiful, like Revolut or Linear: fewer, clearer elements and one strong
primary action per view. Smooth motion that explains what changed. Simple charts and honest
progress. And no struggling with small things: every error, empty state and recovery is designed.

## Eight rules every screen follows

1. **Status reads without colour.** Shape and label carry the meaning; colour reinforces it.
   Ready is a solid square (Velvet's brass, the accent's colour in the other three), converting
   pulses, to convert is solid blue, broken is hatched, missing is a hollow ring. Ready and to
   convert differ in lightness too, in every scheme.
2. **Motion explains, never decorates.** Hover and press 120 ms, toggles and chips 200 ms, panels
   and pages 320 ms, charts on first view 600 to 900 ms. One curve, `cubic-bezier(.2,.8,.2,1)`:
   a quick start and a soft landing. With Windows' animation effects off, nothing moves.
3. **Charts stay simple.** Label the data, not an axis. One accent per chart, neutral grey for the
   rest. No 3D, no gradients, no dual axes.
4. **Progress says what, how far and how long.** Every long job shows its stage, a percentage and
   the time left, and can be paused. Nothing spins silently.
5. **Nothing changes until you review it.** Renames, moves, deletions and conversions are proposed
   as a before and after, applied on approval, logged, and undoable. Duplicates go to quarantine.
6. **Fits every window size.** Compact under 900 px, standard 900 to 1440, wide above. Layouts
   reflow on their own: the nav rail folds into a row on top, panels stack, grids change columns.
   Only the page scrolls: the nav rail and the page's top (`page-top`: its title or breadcrumb)
   stay where they are.
7. **Light and dark, in every scheme.** Each scheme's dark is near-black and its light near-white,
   both tinted by its colour; in light, panels lift with a soft shadow of the scheme's own ink.
   Maku is light or dark as Windows is, unless the owner picks one in Settings › General ("Light
   or dark", beside "Colours"). Body text keeps 4.5:1 contrast in all four schemes, dark and
   light, and status keeps its shapes (in light, a ready square gets a darker edge). The featured
   panel keeps its scheme's deep colour in both, and a part that must stay dark, such as a video,
   says so (`scheme-dark`).
8. **Keyboard first, mouse friendly.** Everything can be reached and done from the keyboard, the
   focus ring is always visible, and click targets are at least 40 px. Two shortcuts where they
   pay off: Space pauses the queue, and 1 to 3 picks a guess on "Which title is this?". No others.

## The four schemes

Each scheme sets every colour token, in dark and in light; nothing else changes between them.
Velvet is the default. Values are dark / light.

| Scheme | Its colours | Window | Accent | Ready | Featured panel |
| --- | --- | --- | --- | --- | --- |
| **Velvet** | Wine and crimson, brass for what's ready | #120b0e / #f6efea | crimson #c8374f / #b52f48 | brass #d6a84f / #c9973a | wine #3b0d1b, a brass orb |
| **Lagoon** | Deep teal, a coral sun | #061113 / #eef5f4 | teal #2cc6b5 / #0d7f74 | #2cc6b5 / #13a395 | deep teal #0a3a3f, a coral orb |
| **Dusk** | Indigo and coral pink | #0c0a16 / #f3f1fa | coral pink #ff6f91 / #c92d62 | #ff6f91 / #e0477a | indigo #23175a, a coral orb |
| **Graphite** | Black and white, nothing else | #0d0e10 / #f4f4f3 | white #ececee / black #16171a | #ececee / #2a2c31 | #1c1f24, a silver orb |

To convert is a blue in every scheme (Dusk's leans violet, beside its pink), broken a hatched red
(Dusk's an orange), missing a hollow grey. Every value is in
[tokens.css](../app/src/styles/tokens.css), one block per scheme (`--scheme-*`).

How it fits together: every colour token reads its scheme's (`--color-accent:
var(--scheme-accent)`), and the scheme is picked by `data-scheme` on `<html>` (Velvet when there's
none). The shell keeps the owner's choice (`app/src-tauri/src/look.rs`) and tells the page before
its first frame (`window.__MAKU_SCHEME__`), so it never shows another scheme first; the window's
own colour under the page follows the scheme too. Settings › General's "Colours"
(`components/scheme-picker.tsx`) changes it at once (`lib/look.ts`).

## The tokens

The tokens live in [app/src/styles/tokens.css](../app/src/styles/tokens.css); Tailwind turns them
into classes, and Tailwind's own palette is switched off so nothing off-system creeps in. A colour
that differs in light is written `light-dark(light, dark)` in each scheme, so one class serves
every scheme in both.

| For | Use | What it is |
| --- | --- | --- |
| The window | `bg-window` | Near-black, or near-white in light, tinted by the scheme |
| A panel | `bg-glass border border-edge rounded-22 shadow-panel` | The scheme's text colour at 4.5% with a faint border; in light, a near-white sheet with a soft shadow |
| A dialog | `bg-dialog rounded-28 shadow-dialog` | A solid, slightly lifted surface |
| Main text, secondary, footnotes | `text-fg`, `text-fg-muted`, `text-fg-faint` | Near-white in dark, ink in light |
| Labels and inactive controls | `text-fg-soft` | Between main and secondary |
| The primary action | `bg-accent text-on-accent` | The scheme's accent, with the text colour it sets for it |
| Accent text, selected state | `text-accent-fg`, `bg-accent/12` | The accent made readable as text; the accent at 12% |
| A secondary button or a field | `bg-field border border-field-edge` | A faint fill and border |
| Behind segmented choices and tabs | `bg-well` | A recessed fill |
| Lines between rows | `border-rule` | A faint line |
| A chip, a tag, a hover, a box inside a panel | `bg-tint/6` (and /3 to /12) | White on dark, ink on light, at that share |
| A tag on artwork | `bg-tag` | The window, see-through |
| Status swatches | `status-ready`, `status-converting`, `status-convert`, `status-broken`, `status-missing` | Solid, pulsing, blue, hatched, hollow; ready with a darker edge in light |
| Asking before something that's hard to take back (Delete, Cancel all, Clear History, emptying a quarantine) | `bg-danger text-on-danger` (the `danger` button), `bg-danger/8` behind the question | The scheme's red (Dusk's orange) |
| The featured panel | `bg-featured` with `bg-featured-orb`, `scheme-dark` | The scheme's deep colour and its orb, dark in both lights |
| Paths, sizes, times | `font-mono` | Geist Mono |
| Headings | `type-title` (32), `type-heading` (20), `type-display` (50) | Manrope 800 |
| Other text | `text-14` (body), `text-13`, `text-12`, `text-11` | Px-named sizes |
| Corners | `rounded-14` to `rounded-24` panels, `rounded-full` buttons and chips | |
| Motion | `ease-cinema`, `duration-120`/`200`/`320`, `animate-fade-up`, `press`, `lift` | |

Rules of thumb:

- One `bg-accent` button per view; everything else is secondary (a field with a border) or ghost.
- Text on the accent is always `text-on-accent` (white on Velvet's crimson, dark on Lagoon's bright
  teal); accent-coloured text is `text-accent-fg`, the accent tuned for text in each scheme, never
  `text-accent`.
- Artwork brings the colour. The interface stays near-black in dark and near-white in light,
  tinted by its scheme, with one accent; colours from posters and stills are not UI tokens.
- No `white/…` or `black/…` on the interface: they don't turn with light mode. Use `tint`, `rule`,
  `field` and `well`. White and black are for what sits on artwork, and for what stays dark: a
  part that must (the featured panel, a video) carries `scheme-dark`, and its tokens resolve dark.
- Never a scheme's colour by value, and nothing that asks which scheme is on: a class built from a
  token is right in all four. The one exception is the scheme picker's swatches, which show each
  scheme's own colours (`SCHEMES` in `lib/look.ts`, the same values as `tokens.css`).
- If a value you need isn't a token, it isn't Maku's yet. Ask before adding one, with its value in
  all four schemes, dark and light.

## Components

Built so far, in `app/src/components/`:

| Component | Use it for |
| --- | --- |
| `ui/button.tsx` | Every button. Variants `primary`, `secondary`, `ghost`, `danger`; sizes `md` (44 px) and `sm` (36 px); `asChild` to style a link |
| `empty-state.tsx` | A place with nothing in it yet, with its one next step |
| `shell/` | The title bar, nav rail, update card and the notes at the window's foot (offline, what the engine tells of) around every screen |
| `maku-logo.tsx` | The mark: a stage curtain drawn back, on a tile in the scheme's accent |
| `scheme-picker.tsx` | The four schemes as cards, each with its swatch, in Settings › General |
| `tmdb-key.tsx` | The box for the TMDB key, and the notice where nothing can be found without one |
| `tmdb-credit.tsx` | TMDB's credit line with its logo, as its terms ask |

New primitives start from shadcn/ui (accessible, built on Radix) and are restyled to Maku's
tokens; see [stack/tailwind.md](stack/tailwind.md). Kura's boards show the rest: radio cards,
switches, segmented controls, chips, progress bars and rings, the episode map, poster cards, review
lists (before → after), toasts with Undo, and dialogs.

## Patterns from the boards

- **Page header**: `type-title`, a one-line summary under it in `text-fg-muted`, the page's primary
  action on the right.
- **A long job**: stage steps (done, current pulsing, next hollow), a bar or ring with the
  percentage, and "18 min left". Pause is always there.
- **Review before apply**: the proposed change as old name → new name in Geist Mono, grouped, with
  counts; "Apply 30 changes" as the one primary button; Undo afterwards in a toast and in History.
- **The small things** (Kura's board 5.3): a drive unplugged, not enough space, a file in use, a
  crash, a failed conversion, a name already taken, offline, a name Windows can't use, and Maku's
  own, no TMDB key yet. Each message names the problem, says what Maku already did, and offers the
  next step.

## Words

- Plain words, short sentences, second person: "Your shelf is empty".
- Say what happens: "Maku closes, updates and opens again", not "Applying update".
- Numbers carry their units and stay human: "18 min left", "≈ 4.2 GB per film", "today 14:20".
- No exclamation marks, no blame, no jargon (say "picture" and "sound", not "video stream").
- A title is a "TV series" or a "Movie"; the films TMDB keeps together are a "collection"; the
  review screen is "Which title is this?", and a video that's neither a series nor a film is "set
  aside". Media server apps are never named: Maku gives files "clean names".

## The design pages

[design/](design/index.html) holds the Maku Design canvas as plain pages, written by
`scripts/design-snapshot.mjs`: [index.html](design/index.html) is the Names board and
[schemes.html](design/schemes.html) the Colour schemes board, every scheme in dark and light. The
canvas is the source of truth (it's the owner's, and private; the pages are the shared copy). The
pages are generated; don't edit them. When the canvas changes, ask Claude to read it (its
`project/` files) into a folder, then:

```powershell
node scripts/design-snapshot.mjs --design <folder>
```

The README's pictures are in [readme/](readme/): `download.svg`, the README's download button
(Velvet's crimson pill, its words drawn as outlines so it looks the same wherever the README is
read), and Maku's own screens. Like the boards, they show made-up titles only: no real series,
film, artwork or video, and no media server app named.

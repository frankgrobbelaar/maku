# Tailwind, shadcn/ui, icons and fonts (styling)

[Tailwind CSS 4](https://tailwindcss.com) styles the UI from Maku's tokens. New components start
from [shadcn/ui](https://ui.shadcn.com) (copied into the repo, built on
[Radix](https://www.radix-ui.com) primitives) and are restyled to Maku's tokens. Icons are
[Lucide](https://lucide.dev); fonts come from [Fontsource](https://fontsource.org) so they work
offline.

## The tokens

`app/src/styles/tokens.css` holds Maku's tokens: Kura's sizes, radii and motion, and colours that
each read the scheme chosen (`--color-accent: var(--scheme-accent)`), with one block of values per
scheme, picked by `data-scheme` on `<html>` (see [../design.md](../design.md)). The `@theme` block
makes each token classes:

- `--color-accent` → `bg-accent`, `text-accent`, `border-accent`, `fill-accent`, with opacity
  modifiers like `bg-accent/12`.
- `--text-13` → `text-13`; `--radius-22` → `rounded-22`.
- `--breakpoint-standard` (900 px) and `--breakpoint-wide` (1440 px) → `standard:` and `wide:`.
- `--ease-cinema`, `--animate-fade-up`… → `ease-cinema`, `animate-fade-up`.

Tailwind's own colours, sizes, radii, shadows and breakpoints are switched off (`--color-*:
initial`…), so `bg-blue-500` or `text-sm` simply don't exist. Spacing keeps Tailwind's 4 px steps
(`p-5` is 20 px, `gap-4.5` is 18 px).

`app/src/styles/global.css` imports Tailwind and the tokens, then adds:

- base styles: light or dark as the window is, body font and size, the focus ring in the scheme's
  accent, thin scrollbars, and no motion when Windows' animation effects are off;
- `press` (hover and press feedback) and `lift` (cards rising on hover);
- `status-ready`, `status-converting`, `status-convert`, `status-broken`, `status-missing`;
- type roles: `type-display`, `type-hero`, `type-title`, `type-heading`, `type-eyebrow`.

When adding a token, also add size and radius names to `fontSizes` and `radii` in
`app/src/lib/utils.ts` (a test fails if they drift), so `cn()` merges them correctly.

## cn()

`cn()` (in `lib/utils.ts`) joins class names and resolves conflicts, so a component's defaults
can be overridden: `cn("text-13", className)`. It uses tailwind-merge, taught Maku's px-named
scales; without that it would mistake `text-13` for a colour and drop it.

## shadcn/ui and Radix

`app/components.json` configures the shadcn CLI (aliases, CSS file, Lucide). To add a component:

```powershell
cd app; pnpm dlx shadcn@latest add switch
```

It lands in `src/components/ui/` as our own code. Then make it Maku's: shadcn's colour names
(`bg-primary`, `text-muted-foreground`, `border-input`…) don't exist here, so map them:

| shadcn | Maku |
| --- | --- |
| `bg-background`, `text-foreground` | `bg-window`, `text-fg` |
| `bg-primary`, `text-primary-foreground` | `bg-accent`, `text-on-accent` |
| `bg-secondary`, `bg-muted` | `bg-field` (a field or button), `bg-well` (behind choices) |
| `text-muted-foreground` | `text-fg-muted` |
| `bg-accent` (hover rows) | `bg-tint/8` |
| `bg-card`, `bg-popover` | `bg-glass`, `bg-dialog` |
| `border`, `border-input` | `border-edge`, `border-field-edge` |
| `ring-ring` | the global focus ring |
| `bg-destructive` | `bg-danger text-on-danger` |
| `rounded-md`, `rounded-lg` | `rounded-14`, `rounded-18` (buttons and chips: `rounded-full`) |

Check the result against the boards, in each scheme, light and dark, and run `pnpm check`. Radix
supplies keyboard handling, focus management and ARIA, so keep its structure and change only the
styling. The CLI may add CSS to `global.css`; keep only what the component needs.

`ui/button.tsx` shows the pattern: shadcn's structure, `cva` variants, Maku's classes.
`ui/switch.tsx` (the setup's toggles) and `ui/segmented.tsx` (one choice from a few, such as
"Same as Windows", "Light" or "Dark") are small wrappers written straight on Radix's Switch and
ToggleGroup, with no shadcn code in them; the setup's standard cards use Radix's RadioGroup, and
the scheme picker (`components/scheme-picker.tsx`) Radix's ToggleGroup, the same way.

## Icons

`lucide-react`, imported one by one (`import { House } from "lucide-react"`). The boards use 1.8
to 2.4 px strokes at 14 to 22 px. Decorative icons get `aria-hidden="true"`; icon-only buttons get
an `aria-label`.

## Fonts

`@fontsource-variable/manrope` and `@fontsource-variable/geist-mono` are imported in `main.tsx`,
so Vite bundles the font files and Maku never fetches fonts from the internet. Families in CSS:
`"Manrope Variable"` and `"Geist Mono Variable"` (the `font-sans` and `font-mono` tokens).

## Upgrading

Keep `tailwindcss` and `@tailwindcss/vite` on the same version. After an upgrade, open each screen
built so far and compare with its board.

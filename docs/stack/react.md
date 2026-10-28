# React, TypeScript and Vite (the UI)

The UI is a single-page app: [React 19](https://react.dev) components in
[TypeScript 7](https://www.typescriptlang.org), served and bundled by [Vite 8](https://vite.dev),
with [React Router 8](https://reactrouter.com) for sections, [TanStack Query 5](https://tanstack.com/query)
for engine data and [Biome 2](https://biomejs.dev) for lint and format.

## Files

```
app/
  index.html            the page Vite serves
  vite.config.ts        Vite plugins, the dev server, Vitest
  tsconfig.json         strict TypeScript, the @/ alias
  biome.json            lint and format rules
  components.json       shadcn/ui settings (see tailwind.md)
  src/
    main.tsx            fonts, styles, the colour scheme before the first frame, render <App/>
    app.tsx             providers and routes
    components/         shared UI: ui/ primitives, shell/ (title bar, nav rail, update card)
    features/           screens, one folder per area (home/, tidy/, convert/…)
    lib/                engine.tsx (status, API calls, types), look.ts (light or dark, the
                        scheme), links.ts, updates.ts, utils.ts
    styles/             tokens.css (the four schemes), global.css
    test/setup.ts       Vitest setup
```

## How it runs

- `pnpm dev` starts Vite on port 1420; `pnpm tauri dev` does that and opens it in Maku's window.
- `pnpm build` type-checks with `tsc`, then bundles into `app/dist/`, which the shell embeds.
  Vite also writes `dist/.vite/licenses.json`: every bundled package with its licence, for the
  third-party notices (`build.license` in `vite.config.ts`).
- `resolve.tsconfigPaths` lets Vite follow the `@/*` alias from `tsconfig.json`.

## Data from the engine

`lib/engine.tsx` is the only place that knows how to reach the engine:

- `EngineProvider` asks the shell for the engine's status, then follows `engine-status` events.
  `useEngine()` returns `starting`, `ready` (address and token) or `failed`.
- `callEngine(engine, path)` adds the token and turns error answers into `EngineError`.
- `useEngineQuery<T>(path)` wraps a TanStack Query around one endpoint and waits until the engine
  is ready. Each endpoint gets a named hook (`useHealth`) and a type that mirrors
  `engine/openapi.json`.

Use the query's `isPending`, `isError` and `data` to draw the loading, error and loaded states.
Writes will use `useMutation` and invalidate the queries they change.

Types are written by hand because the OpenAPI type generators don't support TypeScript 7 yet; a
test in the engine fails when the API changes, which is the cue to update them. Switch to
generated types (openapi-typescript) once it supports TypeScript 7.

## Routing

`HashRouter` keeps the current section in the address's `#`, so a reload in development stays put
and the installed app needs no server rewrites. Routes are in `app.tsx`; the nav rail reads
`components/shell/sections.ts`.

## TypeScript 7

TypeScript 7 is the native (Go) compiler: `tsc` checks the whole UI in well under a second. It has
no JavaScript API yet, so tools that need one (typescript-eslint, openapi-typescript) can't run;
that is why Biome lints. `tsconfig.json` is strict, adds `noUncheckedIndexedAccess`, and only
loads `vite/client` types.

## Biome

One tool for lint, format and import sorting (`biome.json`, the recommended preset). It reads
`.gitignore` from the repo root, skips `src-tauri/` and `dist/`, and understands Tailwind's CSS
directives. Biome formats Markdown and YAML too since 2.6, but it leaves the guides (`*.md`),
written by hand like every other doc, and `pnpm-lock.yaml`, which is pnpm's, as they are.

```powershell
pnpm lint      # check
pnpm fix       # format and apply safe fixes
```

Suppress a rule only with a reason, as `global.css` does for `!important` in the reduced-motion rule.

## Upgrading

`pnpm update --latest`, then `pnpm check` and `pnpm build`. Vite plugins (`@vitejs/plugin-react`,
`@tailwindcss/vite`) must support the installed Vite major. Run `pnpm biome migrate --write` after
a Biome upgrade.

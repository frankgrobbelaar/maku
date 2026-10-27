# Docs: guide for coding agents

Maku's docs are short pages, one subject each, written for the owner and for agents. Start with
[../AGENTS.md](../AGENTS.md).

## Rules

- **Lean.** Say it once, in the right place, in plain short sentences. Use tables for lookups and
  code blocks for commands. No filler, no marketing, no history of how a page came to be.
- **Same commit as the code.** A change that alters how something works updates its doc too.
- **Every tool has a page** in `stack/`: what Maku uses it for, the files, the patterns, the
  commands, gotchas and upgrading. New tool, new page (or a section in the closest page), plus a
  row with its version in the table in [README.md](README.md).
- **Decisions live in [CLAUDE.md](../CLAUDE.md)**, the owner's preferences included. Docs explain
  how things work; CLAUDE.md records what was decided.
- **Links are relative** and must resolve; anchors too.
- **Series and films only.** Maku is for TV series and movies, and its docs' words and examples
  are about nothing else. Kura, Maku's sibling, is named where Maku's foundations come from.
- **`design/` is generated.** `scripts/design-snapshot.mjs` writes it from the Maku Design canvas
  (its Names and Colour schemes boards); never edit those pages by hand. When the canvas changes,
  refresh them (see [design.md](design.md#the-design-pages)). Screens themselves follow Kura's
  boards, in Maku's words and colours.
- **Public pictures use made-up titles.** The README's pictures (`readme/`) and the design boards
  show made-up titles (The Harbour Line, Glass Orchard, the Starfall films): no real series, film,
  artwork or video, and no media server app named. Any new one keeps to that.

## Where things go

| Subject | Page |
| --- | --- |
| How the parts fit and talk | `architecture.md` |
| Setting up, running, checking, updating dependencies | `development.md` |
| How code is written | `conventions.md` |
| How Maku looks and behaves | `design.md` |
| Versions, installer, updates, the signing key | `releasing.md` |
| One tool, in depth | `stack/<tool>.md` |

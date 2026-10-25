# OceanX brand mark v2 — 波浪 X

Status: proposal, 2026-10-25. Not wired into the app yet; this folder is a
self-contained asset set.

## Concept

Two swell trains cross: each diagonal of the X is a gentle S-shaped wave.
One train is white, the other pale sea-blue. The name needs no explanation,
and the crossing reads as two currents meeting rather than a generic letter.

Rejected alternatives: crossed ribbons with a centre gap (looks woven but
disappears at 16 px), a single crest (no X), contours (turns into an equals
sign at 16 px), and the previous two-tone gradient X (unequal weights, muddy
at small sizes).

## Geometry

- Mark grid: `24 × 24`, stroke `2.9`, round caps, endpoints at `4.5` / `19.5`.
- White diagonal:  `M4.5 6.8 C8.82 11.25 15.18 12.75 19.5 17.2`
- Aqua diagonal:   `M19.5 6.8 C15.18 11.25 8.82 12.75 4.5 17.2`
- S amplitude is 1.2 on the 24 grid. A calmer 0.8 or a stronger 1.6 are
  cosmetic variants of the same geometry.
- App icon follows the macOS grid: `1024` canvas, `824` rounded body
  (`rx 186`), `560` mark centred (`translate(232 232) scale(23.333)`).

## Colour

| Token | Value | Use |
| --- | --- | --- |
| sea top | `#0F3E58` | app icon gradient top |
| sea bottom | `#08202F` | app icon gradient bottom |
| white | `#F7FBFD` | first diagonal, text on dark |
| aqua | `#8FD3F0` | second diagonal on dark |
| ink | `#12232E` | monochrome mark on light |
| paper | `#F6F4EF` | sidebar / document background |

The aqua diagonal is a browser-safe accent: never place it on a light
background without the ink monochrome version.

## Usage

- **App icon**: `app-icon.svg` is the master (two-colour, S-curved). The
  `app-icon-{16,32}.png` exports use `app-icon-small.svg`: a straight,
  single-colour X with a slightly heavier stroke for optical crispness.
  `app-icon-{64,128,256,512}.png` use the master. `app-icon.icns` and
  `app-icon.ico` are packaging exports.
- **Sidebar / document**: `mark.svg` (inherits `currentColor`) at 20–24 px,
  followed by the wordmark. Do not colour the sidebar mark with the aqua.
- **Web favicon**: `favicon.svg`.
- **Minimum size**: 16 px. Use `app-icon-small.svg` below 48 px; never scale the
  two-colour master down to a favicon.
- **Do not**: add bevels, rims, drop shadows or extra wave lines; stretch the
  mark; place the two-tone version on a light surface.

## Files

| File | Purpose |
| --- | --- |
| `app-icon.svg` | master app icon, 1024 (two-colour, S-curved) |
| `app-icon-small.svg` | 16/32 px optical variant (straight, single-colour) |
| `app-icon.icns` / `app-icon.ico` | macOS / Windows packaging |
| `app-icon-*.png` | exported sizes |
| `mark.svg` | monochrome mark (currentColor) |
| `mark-color.svg` | two-tone mark on dark |
| `favicon.svg` | browser tab |
| `preview.png` | sizes, Dock, sidebar lockups |

## Regenerate

Requires macOS (`sips`, `iconutil`) and Google Chrome:

```sh
./generate-icons.sh
```

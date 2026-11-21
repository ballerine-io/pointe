# Pointe's logo: Chorus

**Chorus** is one orange point, the voice, sending sound out to the agents it reaches. The sound is made of them: five
rings of dots (12, then 18, 24, 30 and 36), each ring set half a step off the last. The gap between rings grows by 1.06
and the dots shrink by 0.87 per ring, so the field thins out the way sound does. The whole field is turned 10 degrees,
so no dot sits on the vertical or the horizontal.

The SVG files in this folder are the sources. They were drawn from plain geometry by a generator script outside the
repository; nothing here is traced or made by an image model. Change the mark there, or edit these files by hand, and
re-export the images listed under "Where each file goes".

## Two drawings

| Drawing | Files | Use it |
|---|---|---|
| **Full**: five rings of dots and the point | `logo.svg`, `logo-on-dark.svg`, `logo-mono.svg`, `lockup.svg`, `lockup-on-dark.svg`, `lockup-mono.svg`, `app-icon.svg`, `app-icon-flat.svg`, `app-icon-tinted.svg` | 48 px high and above |
| **Small**: six dots and the point | `logo-small.svg`, `logo-small-on-dark.svg`, `lockup-small.svg`, `lockup-small-on-dark.svg`, `favicon.svg` | below 48 px, down to 16 px |

Below 48 px the outer rings of the full drawing close into a grey haze; the small drawing keeps the idea at a size a
tab or a header can hold. Never shrink the full drawing below 48 px.

## Where each file goes

| Place | File |
|---|---|
| README, top | `logo.svg`, `logo-on-dark.svg` (by `prefers-color-scheme`) |
| The page's header (`ui.html`) | `assets/logo.svg`: the small drawing, dots in the text colour, put in place of `{{LOGO}}` by `daemon.py` |
| The page's tab and home-screen icon | `favicon.svg`, `favicon-32.png`, `apple-touch-icon.png`, inline in `ui.html` |
| iPhone app header | `ChorusMark` in `ios/Pointe/Assets.xcassets`: `logo-small.svg`, with `logo-small-on-dark.svg` for dark |
| iPhone app icon | `AppIcon`: `app-icon.svg` at 1024 (light and dark), `app-icon-tinted.svg` for the tinted home screen |
| Site header, hub card | `site/pointe/brand/lockup-small.svg`, `lockup-small-on-dark.svg` |
| Site tab and home-screen icon | `site/pointe/brand/favicon.svg`, `favicon-32.png`, `apple-touch-icon.png` |
| Link previews | `docs/social-preview.html`, rendered to `docs/social-preview.png` and `site/pointe/social.png` |
| One ink only (print, embossing, a ground in another colour) | `logo-mono.svg`, `lockup-mono.svg`: every part takes `currentColor` |

The glow and the outward fade belong to the app icon only. The flat marks have neither.

## Rules

- **Clear space.** Keep empty space on every side of at least a quarter of the mark's height (for a lockup, a quarter
  of the lockup's height). Nothing else, text included, goes inside it.
- **Minimum size.** The small drawing at 16 px; the lockup at 24 px high; the full drawing at 48 px.
- **Don't recolour the orange point.** It is `#FF5A01`, the one accent of the brand, in every colour version. The dots
  are warm black `#0A0400` on light grounds and bone `#F7F2F0` on dark ones. The one exception is a one-ink use, where
  the whole mark, point included, takes the one ink.
- **Don't change the drawing.** No added or removed dots or rings, no rotation (the 10-degree turn is deliberate), no
  stretching, outlines, shadows or gradients, no other colour for the dots.
- **Grounds.** White, the light neutrals, or warm black. Not on orange in colour (use the one-ink version in warm black
  there), and not on a busy photograph.

## Contrast

The orange point is a graphic, so WCAG 2.2's 3:1 for non-text contrast applies (1.4.11): it is 3.13:1 on white, 3.01:1
on the page's light surface `#FCFAFA` and 6.52:1 on warm black. The dots are 20.4:1 (warm black on white) and 18.4:1
(bone on warm black). The wordmark in the lockup is the same colour as the dots.

## Licence

The logo files are part of this repository and under its MIT licence, like the code. "Pointe" and this mark name this
project: use them to point at Pointe, not to suggest that a fork or another product is Pointe or is endorsed by it.

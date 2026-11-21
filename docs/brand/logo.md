# Pointe's logo: Chorus

**Chorus** is one orange point, the voice, sending sound out to the agents it reaches. The sound is made of them: five
rings of dots (12, then 18, 24, 30 and 36), each ring set half a step off the last. The gap between rings grows by 1.06
and the dots shrink by 0.87 per ring, so the field thins out the way sound does. The whole field is turned 10 degrees,
so no dot sits on the vertical or the horizontal.

The SVG files in this folder are the sources. They were drawn from plain geometry by generator scripts outside the
repository; nothing here is traced or made by an image model. Change the mark there, or edit these files by hand, and
re-export the images listed under "Where each file goes".

## Three drawings, one mark

Every surface shows many points around the orange one, as the app icon does. Small sizes get fewer rings, never fewer
dots per ring and never a different drawing. All three keep the rules above: six more dots per ring, each ring half a
step off the last, the 10-degree turn, dots shrinking outward, and rings as far apart as neighbours on a ring, so the
dots make one even field.

| Drawing | Rings and dots | Files | Use it |
|---|---|---|---|
| **Full** | five: 12, 18, 24, 30, 36 (120 dots) | `logo.svg`, `logo-on-dark.svg`, `logo-mono.svg`, `lockup.svg`, `lockup-on-dark.svg`, `lockup-mono.svg`, `app-icon.svg`, `app-icon-flat.svg`, `app-icon-tinted.svg` | 48 px high and above |
| **Compact** | four: 12, 18, 24, 30 (84 dots), larger dots, a light outward fade, a larger point | `logo-small.svg`, `logo-small-on-dark.svg`, `lockup-small.svg`, `lockup-small-on-dark.svg` | 24 to 47 px: headers, lockups |
| **Favicon** | three: 10, 16, 22 (48 dots), no fade, bone on the app icon's warm black squircle | `favicon.svg` | 16 to 32 px: browser tabs |

Below 48 px the full drawing's outer rings close into a grey haze; below 24 px the compact one does. Never shrink a
drawing below its row, and never use a mark with fewer dots: the six-dot drawing that stood here before is retired.
`tests/test_brand.py` counts the dots in every mark in the repository.

## Where each file goes

| Place | File |
|---|---|
| README, top | `logo.svg`, `logo-on-dark.svg` (by `prefers-color-scheme`) |
| The page's header (`ui.html`) | `assets/logo.svg`: the compact drawing, dots in the text colour, put in place of `{{LOGO}}` by `daemon.py` |
| The page's tab and home-screen icon | `favicon.svg`, `favicon-32.png` (the favicon drawing), `apple-touch-icon.png` (the full app icon at 180), inline in `ui.html` |
| iPhone app header | `ChorusMark` in `ios/Pointe/Assets.xcassets`: `logo-small.svg`, with `logo-small-on-dark.svg` for dark |
| iPhone app icon | `AppIcon`: `app-icon.svg` at 1024 (light and dark), `app-icon-tinted.svg` for the tinted home screen |
| Site header, hub card | `site/pointe/brand/lockup-small.svg`, `lockup-small-on-dark.svg` |
| Site tab and home-screen icon | `site/pointe/brand/favicon.svg`, `favicon-32.png`, `apple-touch-icon.png`, the same three |
| Link previews | `docs/social-preview.html`, rendered to `docs/social-preview.png` and `site/pointe/social.png`: the compact lockup top left, the full drawing on the right |
| One ink only (print, embossing, a ground in another colour) | `logo-mono.svg`, `lockup-mono.svg`: every part takes `currentColor` |

The glow belongs to the app icon only. The outward fade belongs to the app icon and, lighter, to the compact drawing,
where it keeps the field from reading as one grey disc; the full flat marks and the favicon have none.

## Rules

- **Clear space.** Keep empty space on every side of at least a quarter of the mark's height (for a lockup, a quarter
  of the lockup's height). Nothing else, text included, goes inside it.
- **Minimum size.** The favicon drawing at 16 px; the compact drawing and the lockup at 24 px high; the full drawing at
  48 px.
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

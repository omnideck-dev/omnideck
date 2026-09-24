# Bundled fonts

Both fonts are licensed under the SIL Open Font License 1.1; see
[JetBrainsMono-OFL.txt](../../../public/assets/licenses/JetBrainsMono-OFL.txt) and
[Inter-OFL.txt](../../../public/assets/licenses/Inter-OFL.txt) for the copyright and license.
Vite copies both license files into the distributable UI.

## JetBrains Mono (code)

Source: [Google Fonts JetBrains Mono](https://github.com/google/fonts/tree/5e35378e6bda803962ee6fd257e444a7d459660d/ofl/jetbrainsmono),
`JetBrainsMono[wght].ttf`, converted without subsetting to WOFF2 using
FontTools 4.59.2 (`TTFont`, `recalcTimestamp=False`, `flavor="woff2"`).
The stylesheet exposes the existing normal weights 400–600 with `font-display: swap`.

## Inter (brand / body)

Source: [Google Fonts Inter](https://github.com/google/fonts/tree/0b58fb370093f9a9f4ff785d94405710b79de67c/ofl/inter),
`Inter[opsz,wght].ttf`. The `wght` axis was restricted to 400–700 with
`fonttools varLib.instancer` (the `opsz` axis is left variable so browsers keep auto optical
sizing), then converted to WOFF2 using FontTools 4.65.0 (`TTFont`, `recalcTimestamp=False`,
`flavor="woff2"`). The stylesheet exposes weights 400–700 with `font-display: swap`.

Vite bundles and hashes both assets; no font service is contacted at runtime.

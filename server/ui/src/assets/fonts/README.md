# Bundled font

JetBrains Mono is licensed under the SIL Open Font License 1.1; see
[JetBrainsMono-OFL.txt](../../../public/assets/licenses/JetBrainsMono-OFL.txt) for the copyright
and license. Vite copies the license into the distributable UI.

Source: [Google Fonts JetBrains Mono](https://github.com/google/fonts/tree/5e35378e6bda803962ee6fd257e444a7d459660d/ofl/jetbrainsmono),
`JetBrainsMono[wght].ttf`, converted without subsetting to WOFF2 using
FontTools 4.59.2 (`TTFont`, `recalcTimestamp=False`, `flavor="woff2"`).
The stylesheet exposes the existing normal weights 400–600 with `font-display: swap`.
Vite bundles and hashes the asset; no font service is contacted at runtime.

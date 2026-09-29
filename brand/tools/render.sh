#!/usr/bin/env bash
# Rasterise the brand SVGs into brand/png/. Needs rsvg-convert (librsvg).
# The mark sits on a 16-cell grid, so every icon size (48..1024) lands its
# cells on whole pixels: 3, 4, 8, 16, 32, 64 px per cell.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p png
for s in 48 64 128 256 512 1024; do
  rsvg-convert -w "$s" -h "$s" mark-dark.svg -o "png/icon-$s.png"
done
rsvg-convert -w 1280 -h 640 social-preview.svg -o png/social-preview-1280x640.png
rsvg-convert -w 1600 logo-dark.svg -o png/logo-dark-1600.png
rsvg-convert -w 1600 logo-light.svg -o png/logo-light-1600.png
echo "rendered: $(ls png | tr '\n' ' ')"

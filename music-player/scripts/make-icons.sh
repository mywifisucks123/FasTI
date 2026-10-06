#!/usr/bin/env bash
# Erzeugt die PNG-Icons aus public/icons/icon.svg (braucht ImageMagick oder rsvg-convert).
set -euo pipefail
cd "$(dirname "$0")/../public/icons"
render() {
  if command -v rsvg-convert >/dev/null; then rsvg-convert -w "$1" -h "$1" icon.svg -o "$2"
  else convert -background none -density 300 icon.svg -resize "$1x$1" "$2"; fi
}
render 180 apple-touch-icon.png
render 192 icon-192.png
render 512 icon-512.png
# Maskable: iOS/Android schneiden selbst zu, Motiv liegt schon in der Safe-Zone
cp icon-512.png icon-maskable-512.png
echo "Icons erzeugt."

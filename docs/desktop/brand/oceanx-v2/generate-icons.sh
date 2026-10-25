#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
for name in app-icon app-icon-small; do
  cat > "$tmp/render-$name.html" <<EOF
<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:transparent}img{display:block;width:1024px;height:1024px}
</style></head><body><img src="file://$PWD/$name.svg"></body></html>
EOF
  "$CHROME" --headless=new --no-sandbox --disable-gpu --hide-scrollbars \
    --default-background-color=00000000 --user-data-dir="$tmp/profile-$name" \
    --force-device-scale-factor=1 --window-size=1024,1024 \
    --screenshot="$tmp/$name-1024.png" "file://$tmp/render-$name.html" >/dev/null 2>&1
done
# 16/32 use the single-colour optical variant; 64+ use the two-colour master.
sips -z 32 32 "$tmp/app-icon-small-1024.png" --out "$tmp/icon-32.png" >/dev/null
sips -z 16 16 "$tmp/app-icon-small-1024.png" --out "$tmp/icon-16.png" >/dev/null
sips -z 64 64 "$tmp/app-icon-1024.png" --out "$tmp/icon-64.png" >/dev/null
rm -rf app-icon.iconset && mkdir app-icon.iconset
for s in 128 256 512 1024; do
  sips -z "$s" "$s" "$tmp/app-icon-1024.png" --out "$tmp/icon-$s.png" >/dev/null
done
cp "$tmp/icon-16.png"   app-icon-16.png
cp "$tmp/icon-32.png"   app-icon-32.png
cp "$tmp/icon-64.png"   app-icon-64.png
cp "$tmp/icon-128.png"  app-icon-128.png
cp "$tmp/icon-256.png"  app-icon-256.png
cp "$tmp/icon-512.png"  app-icon-512.png
cp "$tmp/icon-16.png"   app-icon.iconset/icon_16x16.png
cp "$tmp/icon-32.png"   app-icon.iconset/icon_16x16@2x.png
cp "$tmp/icon-32.png"   app-icon.iconset/icon_32x32.png
cp "$tmp/icon-64.png"   app-icon.iconset/icon_32x32@2x.png
cp "$tmp/icon-128.png"  app-icon.iconset/icon_128x128.png
cp "$tmp/icon-256.png"  app-icon.iconset/icon_128x128@2x.png
cp "$tmp/icon-256.png"  app-icon.iconset/icon_256x256.png
cp "$tmp/icon-512.png"  app-icon.iconset/icon_256x256@2x.png
cp "$tmp/icon-512.png"  app-icon.iconset/icon_512x512.png
cp "$tmp/icon-1024.png" app-icon.iconset/icon_512x512@2x.png
iconutil -c icns app-icon.iconset -o app-icon.icns
# Windows .ico via Pillow when available.
python - <<'PY'
try:
    from PIL import Image
    Image.open('app-icon-256.png').save(
        'app-icon.ico', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
except ImportError:
    pass
PY
rm -rf app-icon.iconset
echo "regenerated app-icon.icns / .ico / app-icon-*.png"

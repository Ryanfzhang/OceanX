"""OceanX app icon: a sea in three layers under a paper sky (light) or a night sky (dark).

The surface swell is the largest wave and the two interfaces below it flatten with depth.
Writes oceanx-icon.svg and oceanx-icon-dark.svg on the macOS grid (1024 canvas, 824 body, radius 186)."""
import math
import sys
from pathlib import Path

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
BODY = 'M286 100H738C841 100 924 183 924 286V738C924 841 841 924 738 924H286C183 924 100 841 100 738V286C100 183 183 100 286 100Z'
# base, amplitude, wavelength and phase of the surface and the two interfaces
WAVES = [(492, 46, 800, 0.3), (640, 22, 720, 1.7), (778, 9, 660, 3.0)]
SEA = ('#4C93DB', '#2667B0', '#183F75')
THEMES = {
    'oceanx-icon.svg': (('#FBF9F4', '#EEE8DC'), '#9CC5EE'),
    'oceanx-icon-dark.svg': (('#141C28', '#1C2737'), '#79AEE4'),
}


def wave(base, amp, wavelength, phase, x0=-80, x1=1104, steps=200):
    points = []
    for i in range(steps + 1):
        x = x0 + (x1 - x0) * i / steps
        points.append((x, base + amp * math.sin(2 * math.pi * (x - 512) / wavelength + phase)))
    return 'M' + ' L'.join(f'{x:.1f} {y:.1f}' for x, y in points)


def icon(sky, highlight):
    lines = [wave(*w) for w in WAVES]
    layers = ''.join(f'<path d="{d} L1104 1100 L-80 1100 Z" fill="{colour}"/>' for d, colour in zip(lines, SEA))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">'
            f'<defs><linearGradient id="oceanx-sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{sky[0]}"/>'
            f'<stop offset="1" stop-color="{sky[1]}"/></linearGradient><clipPath id="oceanx-body"><path d="{BODY}"/></clipPath></defs>'
            f'<g clip-path="url(#oceanx-body)"><rect width="1024" height="1024" fill="url(#oceanx-sky)"/>{layers}'
            f'<path d="{lines[0]}" fill="none" stroke="{highlight}" stroke-width="14"/></g></svg>\n')


for name, (sky, highlight) in THEMES.items():
    (out / name).write_text(icon(sky, highlight), encoding='utf-8')
print('icons written to', out)

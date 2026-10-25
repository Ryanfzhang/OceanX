"""Static mocks of the OceanX workspace with the map always open: warm paper (light), deep ocean (dark),
and a figure opened beside the map. Writes self-contained HTML pages into the output folder."""
import math
import sys
from pathlib import Path

from cartopy.io import shapereader
from shapely.geometry import box

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
brand = Path(sys.argv[2])
CORE_LOGO = __import__('base64').b64encode(Path(sys.argv[3]).read_bytes()).decode()
APP_ICON = {theme: (brand / name).read_text(encoding='utf-8') for theme, name in (('light', 'oceanx-icon.svg'), ('dark', 'oceanx-icon-dark.svg'))}
LAT_C = math.cos(math.radians(14))


def xy(lon, lat):
    return lon * LAT_C, -lat


def ring_path(coords):
    pts = [xy(lon, lat) for lon, lat in coords]
    return 'M' + ' L'.join(f'{x:.3f} {y:.3f}' for x, y in pts) + ' Z'


land_paths = []
reader = shapereader.Reader(str(Path.home() / '.local/share/cartopy/shapefiles/natural_earth/physical/ne_50m_land.shp'))
area = box(92, -14, 136, 38)
for geometry in reader.geometries():
    clipped = geometry.intersection(area)
    if clipped.is_empty:
        continue
    polygons = [clipped] if clipped.geom_type == 'Polygon' else list(getattr(clipped, 'geoms', []))
    for polygon in polygons:
        if polygon.geom_type != 'Polygon':
            continue
        polygon = polygon.simplify(0.03, preserve_topology=True)
        d = ring_path(polygon.exterior.coords)
        for interior in polygon.interiors:
            d += ' ' + ring_path(interior.coords)
        land_paths.append(d)
LAND = ' '.join(land_paths)


def curve(points):
    """Smooth path through lon/lat points."""
    p = [xy(*q) for q in points]
    d = [f'M{p[0][0]:.3f} {p[0][1]:.3f}']
    for i in range(len(p) - 1):
        a, b, c, e = p[max(i - 1, 0)], p[i], p[i + 1], p[min(i + 2, len(p) - 1)]
        c1 = (b[0] + (c[0] - a[0]) / 6, b[1] + (c[1] - a[1]) / 6)
        c2 = (c[0] - (e[0] - b[0]) / 6, c[1] - (e[1] - b[1]) / 6)
        d.append(f'C{c1[0]:.3f} {c1[1]:.3f} {c2[0]:.3f} {c2[1]:.3f} {c[0]:.3f} {c[1]:.3f}')
    return ' '.join(d)


# Upper-layer cyclonic gyre (anticlockwise) in four arcs, and the Kuroshio loop through Luzon Strait.
gyre = []
cx, cy, rx, ry = 114.6, 13.6, 4.6, 6.0
for start in (330, 60, 150, 240):  # east side runs north: anticlockwise in map view
    pts = []
    for step in range(9):
        angle = math.radians(start + step * 9)
        pts.append((cx + rx * math.cos(angle), cy + ry * math.sin(angle)))
    gyre.append(curve(pts))
KUROSHIO = curve([(125.9, 13.2), (124.9, 17.0), (123.0, 19.5), (121.4, 20.6), (120.0, 21.0), (120.3, 22.0), (121.9, 22.7), (122.9, 25.2)])


def map_svg(theme, view, label_lat, label_lon, px_per_unit=24.0):
    if theme == 'dark':
        ocean, land, coast, grid, ink, accent, warm = '#1D2024', '#30302E', '#4A4944', 'rgba(222,220,209,.06)', '#9C9A92', '#74ABE2', '#D97757'
        tint = '#74ABE2'
    else:
        ocean, land, coast, grid, ink, accent, warm = '#E3E9EF', '#F0EEE6', '#D1CEC4', 'rgba(31,30,29,.07)', '#73726C', '#2C84DB', '#D97757'
        tint = '#2C84DB'
    x0, y0, w, h = view
    k = 1 / px_per_unit  # user units per screen pixel at the rendered scale
    lines = []
    for lon in range(95, 135, 5):
        x = lon * LAT_C
        lines.append(f'<line x1="{x:.3f}" y1="{y0 - 1}" x2="{x:.3f}" y2="{y0 + h + 1}" vector-effect="non-scaling-stroke"/>')
    for lat in range(-10, 40, 5):
        lines.append(f'<line x1="{x0 - 1}" y1="{-lat}" x2="{x0 + w + 1}" y2="{-lat}" vector-effect="non-scaling-stroke"/>')
    labels = []
    for lon in label_lon:
        labels.append(f'<text x="{lon * LAT_C + 0.15:.3f}" y="{y0 + h - 0.35:.3f}">{lon}°E</text>')
    for lat in label_lat:
        labels.append(f'<text x="{x0 + 0.9:.3f}" y="{-lat - 0.15:.3f}">{lat}°N</text>')
    arrows = ''.join(f'<path d="{d}" vector-effect="non-scaling-stroke" marker-end="url(#a-{theme})"/>' for d in gyre)
    glow = f'<ellipse cx="{cx * LAT_C:.3f}" cy="{-cy:.3f}" rx="{rx * LAT_C * 1.25:.3f}" ry="{ry * 1.2:.3f}" fill="url(#vort-{theme})"/>'
    currents = f'''<g fill="none" stroke-linecap="round" vector-effect="non-scaling-stroke">
    <g stroke="{accent}" stroke-width="2.2" opacity=".9">{arrows}</g>
    <path d="{KUROSHIO}" stroke="{warm}" stroke-width="2.4" vector-effect="non-scaling-stroke" marker-end="url(#w-{theme})" opacity=".95"/>
  </g>'''
    return f'''<svg class="map-svg" viewBox="{x0:.3f} {y0:.3f} {w:.3f} {h:.3f}" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <radialGradient id="vort-{theme}" cx="{cx * LAT_C:.3f}" cy="{-cy:.3f}" r="5.6" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{tint}" stop-opacity=".16"/><stop offset="1" stop-color="{tint}" stop-opacity="0"/>
    </radialGradient>
    <marker id="a-{theme}" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="{accent}"/></marker>
    <marker id="w-{theme}" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="{warm}"/></marker>
  </defs>
  <rect x="{x0 - 2}" y="{y0 - 2}" width="{w + 4}" height="{h + 4}" fill="{ocean}"/>
  <g stroke="{grid}" stroke-width="1" vector-effect="non-scaling-stroke">{''.join(lines)}</g>
  {glow}
  <path d="{LAND}" fill="{land}" stroke="{coast}" stroke-width=".8" vector-effect="non-scaling-stroke" fill-rule="evenodd"/>
  {currents}
  <g fill="{ink}" font-size="{11 * k:.3f}" font-family="-apple-system, BlinkMacSystemFont, sans-serif">{''.join(labels)}</g>
</svg>'''


FULL_VIEW = (104.6 * LAT_C, -31.5, 20.4 * LAT_C, 37.0)
SPLIT_VIEW = (109.2 * LAT_C, -24.2, 16.2 * LAT_C, 12.4)

ICON = {
    'folder': '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 7h6l2 2h10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
    'gear': '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.3 1a7 7 0 0 0-1.7-1L14.5 3h-5l-.4 2.6a7 7 0 0 0-1.7 1l-2.3-1-2 3.4L5 11a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.3-1a7 7 0 0 0 1.7 1l.4 2.6h5l.4-2.6a7 7 0 0 0 1.7-1l2.3 1 2-3.4-2-1.5c.1-.3.1-.7.1-1z"/></svg>',
    'book': '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 19V5"/></svg>',
    'plus': '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 5v14M5 12h14"/></svg>',
    'more': '<svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>',
    'add': '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
    'mic': '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><path d="M12 19v3"/></svg>',
    'pdf': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4M16 13H8M16 17H8M10 9H8"/></svg>',
    'folder_add': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 10v6M9 13h6"/><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>',
    'send': '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>',
    'chart': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M4 19V5"/><path d="M4 19h16"/><path d="m7 15 4-5 3 3 5-7"/></svg>',
    'layers': '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/></svg>',
    'expand': '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></svg>',
    'close': '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M18 6 6 18M6 6l12 12"/></svg>',
    'papers': '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>',
    'data': '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/></svg>',
    'autoresearch': '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>',
}


def chart_svg(theme):
    """Three layer vorticity indices 1993-2018 with the post-2009 regime shaded (illustrative values)."""
    w, h, left, bottom, top, right = 400, 260, 34, 24, 10, 8
    years = list(range(1993, 2019))
    upper = [0.2 + 0.035 * (y - 1993) - (0.06 * (y - 2008) if y > 2008 else 0) + 0.06 * math.sin(y * 1.3) for y in years]
    middle = [-0.4 + 0.018 * (y - 1993) - (0.07 * (y - 2008) if y > 2008 else 0) + 0.05 * math.sin(y * 0.9 + 1) for y in years]
    deep = [0.05 + 0.02 * math.sin(y * 1.1) + (0.075 * (y - 2008) if y > 2008 else 0) for y in years]
    lo, hi = -1.15, 1.0
    def px(i, v):
        return left + i * (w - left - right) / (len(years) - 1), top + (hi - v) * (h - top - bottom) / (hi - lo)
    def line(values):
        return 'M' + ' L'.join(f'{px(i, v)[0]:.1f} {px(i, v)[1]:.1f}' for i, v in enumerate(values))
    muted = '#9C9A92' if theme == 'dark' else '#73726C'
    grid = 'rgba(222,220,209,.08)' if theme == 'dark' else 'rgba(31,30,29,.08)'
    shade = 'rgba(222,220,209,.05)' if theme == 'dark' else 'rgba(31,30,29,.04)'
    colours = ('#74ABE2', '#D97757', '#9C9A92') if theme == 'dark' else ('#2C84DB', '#D97757', '#73726C')
    x2009 = px(years.index(2009), 0)[0]
    ticks = ''.join(f'<text x="{px(years.index(y), 0)[0]:.1f}" y="{h - 6}" text-anchor="middle">{y}</text>' for y in (1995, 2000, 2005, 2010, 2015))
    hlines = ''.join(f'<line x1="{left}" x2="{w - right}" y1="{px(0, v)[1]:.1f}" y2="{px(0, v)[1]:.1f}"/>' for v in (-1, -0.5, 0, 0.5, 1))
    yt = ''.join(f'<text x="{left - 6}" y="{px(0, v)[1] + 3.5:.1f}" text-anchor="end">{v:g}</text>' for v in (-1, 0, 1))
    return f'''<svg viewBox="0 0 {w} {h}" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="-apple-system, BlinkMacSystemFont, sans-serif" font-size="10.5">
  <rect x="{x2009:.1f}" y="{top}" width="{w - right - x2009:.1f}" height="{h - top - bottom}" fill="{shade}"/>
  <g stroke="{grid}">{hlines}</g>
  <g fill="{muted}">{ticks}{yt}<text x="{x2009 + 6:.1f}" y="{top + 12}">2009 年后</text></g>
  <g fill="none" stroke-width="2" stroke-linejoin="round" stroke-linecap="round">
    <path d="{line(upper)}" stroke="{colours[0]}"/><path d="{line(middle)}" stroke="{colours[1]}"/><path d="{line(deep)}" stroke="{colours[2]}"/>
  </g>
</svg>''', colours


CSS = '''
:root{
  /* Claude Code's colours: bg-200/100/000, text-100/300/500, border at 10 and 15 percent, brand, blue, success */
  --bg:#F5F4ED; --paper:#FAF9F5; --card:#FFFFFF; --ink:#141413; --muted:#3D3D3A; --faint:#73726C;
  --line:rgba(31,30,29,.10); --line-strong:rgba(31,30,29,.15); --hover:#F0EEE6; --selected:#E8E6DC;
  --accent:#C6613F; --blue:#2C84DB; --green:#2F7613; --bubble:#F0EEE6; --lights:#DEDCD3;
  --chip:rgba(255,255,255,.92); --shadow:0 1px 2px rgba(0,0,0,.04),0 4px 20px rgba(0,0,0,.035);
  /* Claude Code's stack after its own typeface: system Latin, PingFang for Chinese, YaHei on Windows */
  --sans:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","PingFang TC","Hiragino Sans","Microsoft YaHei",sans-serif;
}
.dark{
  --bg:#1F1E1D; --paper:#262624; --card:#30302E; --ink:#FAF9F5; --muted:#C2C0B6; --faint:#9C9A92;
  --line:rgba(222,220,209,.10); --line-strong:rgba(222,220,209,.15); --hover:#30302E; --selected:#3A3A37;
  --accent:#D97757; --blue:#74ABE2; --green:#65BB30; --bubble:#141413; --lights:#3A3A37;
  --chip:rgba(48,48,46,.92); --shadow:0 1px 2px rgba(0,0,0,.25),0 4px 20px rgba(0,0,0,.25);
}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{font-family:var(--sans);color:var(--ink);background:var(--bg);-webkit-font-smoothing:antialiased}
.app{display:grid;grid-template-columns:248px minmax(0,1fr) clamp(400px,33vw,560px);height:100vh;overflow:hidden;background:var(--bg)}
/* sidebar */
.side{display:flex;flex-direction:column;min-height:0;padding:0 12px 12px}
.titlebar{height:52px;display:flex;align-items:center;gap:8px;flex:0 0 auto}
.lights{display:flex;gap:8px;padding-left:8px;margin-right:14px}
.lights i{width:12px;height:12px;border-radius:50%;background:var(--lights)}
/* the window controls have the top row to themselves; the brand lives in the app icon and the welcome page */
.sect{display:flex;align-items:center;justify-content:space-between;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--faint);padding:0 8px;margin:14px 0 6px}
.sect svg{color:var(--faint)}
.item{display:flex;align-items:center;gap:9px;height:32px;padding:0 8px;border-radius:8px;color:var(--ink);font-size:14px;white-space:nowrap;overflow:hidden}
.item span{overflow:hidden;text-overflow:ellipsis}
.item svg{color:var(--faint);flex:0 0 auto}
.item.task{padding-left:32px}
.side.web .item.task{padding-left:8px}
.webbrand{display:flex;align-items:center;gap:9px;height:52px;padding:0 8px;font-size:15px;font-weight:600;flex:0 0 auto}
.webbrand svg{width:22px;height:22px;display:block}
.item.active{background:var(--selected);font-weight:500}
.dot{width:6px;height:6px;border-radius:50%;background:var(--green);flex:0 0 auto;margin-left:auto}
.spin{width:11px;height:11px;border-radius:50%;border:1.6px solid var(--line-strong);border-top-color:var(--accent);flex:0 0 auto;margin-left:auto}
.spacer{flex:1}
.foot{display:flex;gap:2px}
.foot span{display:flex;align-items:center;gap:8px;height:32px;padding:0 8px;border-radius:8px;color:var(--muted);font-size:13px}
/* conversation */
.main{display:flex;flex-direction:column;min-width:0;background:var(--paper)}
.top{height:52px;flex:0 0 auto;display:flex;align-items:center;gap:12px;width:min(680px,calc(100% - 64px));margin:0 auto}
.top h1{font-size:15px;font-weight:500;margin:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.status{display:flex;align-items:center;gap:6px;font-size:12.5px;color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}
.pulse{width:7px;height:7px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 4px color-mix(in srgb,var(--accent) 14%,transparent)}
.top .more{margin-left:auto;color:var(--faint);display:grid;place-items:center;width:30px;height:30px;border-radius:8px}
.scroll{flex:1;overflow:hidden}
.column{width:min(680px,calc(100% - 64px));margin:0 auto;padding:18px 0 0}
.turn{display:flex;flex-direction:column;gap:18px;padding-bottom:30px}
.user{display:flex;justify-content:flex-end}
.bubble{max-width:540px;background:var(--bubble);border-radius:16px 16px 4px 16px;padding:12px 16px;font-size:16px;line-height:24px}
.prose{font-size:16px;line-height:24px}
.prose p{margin:0 0 14px}.prose p:last-child{margin-bottom:0}
.prose h3{font-size:17px;font-weight:580;line-height:24px;margin:24px 0 8px}
.prose b{font-weight:580}
.act{display:flex;align-items:center;gap:9px;font-size:13px;color:var(--muted)}
.act .check{color:var(--green);font-size:12px;width:14px}
.act .run{width:14px;display:grid;place-items:center}.act .run i{width:7px;height:7px;border-radius:50%;background:var(--accent);animation:none;box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 16%,transparent)}
.act .obj{color:var(--faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.act .time{margin-left:auto;font-variant-numeric:tabular-nums;color:var(--faint);font-size:12px;white-space:nowrap}
.act .details{color:var(--faint);font-size:12px;white-space:nowrap}
.result{display:flex;align-items:center;gap:12px;padding:12px 4px;border-top:1px solid var(--line)}
.ricon{width:32px;height:32px;border-radius:8px;background:var(--hover);display:grid;place-items:center;color:var(--muted);flex:0 0 auto}
.rt{display:flex;flex-direction:column;gap:2px;min-width:0}
.rt b{font-size:14px;font-weight:500}
.rt span{font-size:12px;color:var(--faint)}
.go{margin-left:auto;color:var(--faint);font-size:12.5px;white-space:nowrap}
.result.open .go{color:var(--blue)}
.composer-wrap{flex:0 0 auto;padding:12px 0 20px}
.composer{width:min(680px,calc(100% - 64px));margin:0 auto;background:var(--card);border:1px solid var(--line-strong);border-radius:16px;padding:14px 14px 10px;box-shadow:var(--shadow)}
.ph{font-size:14.5px;color:var(--faint);padding:2px 4px 16px}
.crow{display:flex;align-items:center;gap:8px;color:var(--faint)}
.crow small{font-size:12.5px}
.send{width:30px;height:30px;border-radius:50%;background:var(--accent);color:#fff;display:grid;place-items:center}
.cbtn{width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:var(--muted)}
.cbtn.on{background:var(--hover);color:var(--ink)}
.grow{flex:1}
.proj{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--faint)}
.composer{position:relative}
.menu{position:absolute;left:10px;top:calc(100% + 6px);z-index:3;width:210px;padding:6px;background:var(--card);border:1px solid var(--line-strong);border-radius:12px;box-shadow:var(--shadow)}
.mi{display:flex;align-items:center;gap:10px;height:34px;padding:0 10px;border-radius:8px;font-size:14px;color:var(--ink)}
.mi svg{color:var(--muted)}
.mi.on{background:var(--hover)}
/* the map is a card on the background, always open */
.mapcol{padding:12px;min-width:0;display:flex}
.mapcard{position:relative;flex:1;min-width:0;border-radius:14px;overflow:hidden;border:1px solid var(--line);box-shadow:var(--shadow);background:var(--card);display:flex;flex-direction:column}
.maparea{position:relative;flex:1;min-height:0}
.map-svg{position:absolute;inset:0;width:100%;height:100%;display:block}
.chip{position:absolute;display:flex;align-items:center;gap:7px;padding:6px 10px;border-radius:999px;background:var(--chip);backdrop-filter:blur(8px);font-size:12.5px;color:var(--ink);box-shadow:0 1px 2px rgba(34,33,29,.08)}
.chip small{color:var(--muted);font-size:12px}
.chip svg{color:var(--muted)}
.tl{top:12px;left:12px}.tr{top:12px;right:12px;padding:6px 8px}
.zoom{position:absolute;right:12px;top:52px;display:grid;border-radius:10px;overflow:hidden;background:var(--chip);backdrop-filter:blur(8px);box-shadow:0 1px 2px rgba(34,33,29,.08)}
.zoom span{width:30px;height:28px;display:grid;place-items:center;color:var(--muted);font-size:15px}
.zoom span+span{border-top:1px solid var(--line)}
.legend{left:12px;bottom:12px;border-radius:10px;flex-direction:column;align-items:stretch;gap:5px;padding:8px 10px}
.legend .keys{display:flex;gap:14px;font-size:12px;color:var(--muted)}
.legend .keys i{display:inline-block;width:14px;height:2px;border-radius:1px;vertical-align:middle;margin-right:5px}
.attr{position:absolute;right:12px;bottom:10px;font-size:10.5px;color:var(--faint)}
/* figure sheet under the map */
.sheet{flex:0 0 58%;display:flex;flex-direction:column;border-top:1px solid var(--line);background:var(--card)}
.handle{height:14px;display:grid;place-items:center}.handle i{width:34px;height:4px;border-radius:2px;background:var(--line-strong)}
.sheethead{display:flex;align-items:center;gap:8px;padding:2px 16px 8px}
.kicker{font-size:11px;font-weight:600;letter-spacing:.04em;color:var(--faint)}
.sheethead b{font-size:14px;font-weight:500}
.sheethead .x{margin-left:auto;color:var(--faint);display:flex;gap:10px}
.figure{padding:4px 16px 0}
.figure .cap{font-size:12px;color:var(--muted);line-height:1.6;margin:8px 0 0}
.figlegend{display:flex;gap:16px;font-size:12px;color:var(--muted);padding:6px 0 0}
.figlegend i{display:inline-block;width:14px;height:2px;border-radius:1px;vertical-align:middle;margin-right:6px}
/* welcome: the one place the brand appears inside the window */
.welcome-main{position:relative}
.welcome{width:min(680px,calc(100% - 64px));margin:0 auto;flex:1;display:flex;flex-direction:column;justify-content:center;padding-bottom:9vh}
.greet{display:flex;align-items:center;justify-content:center;gap:14px;margin:0 0 26px}
.greet svg{width:44px;height:44px;display:block;filter:drop-shadow(0 1px 2px rgba(34,33,29,.14))}
.greet h2{font-weight:500;font-size:24px;line-height:30px;margin:0}
.welcome .composer{width:100%}
.entries{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:0 0 14px}
.entry{min-height:96px;display:flex;flex-direction:column;justify-content:space-between;align-items:flex-start;padding:14px 16px;border:1px solid var(--line-strong);border-radius:14px;background:var(--paper)}
.entry svg{color:var(--faint)}
.entry span{font-size:14px;font-weight:500;line-height:20px}
/* no task is open, so there is nothing to show on a map */
.app.nomap{grid-template-columns:248px minmax(0,1fr)}
.ack{position:absolute;left:0;right:0;bottom:20px;display:flex;justify-content:center;align-items:center;gap:10px;font-size:12px;color:var(--faint)}
.ack img{height:24px}
.dark .ack img{filter:brightness(0) invert(1);opacity:.6}
'''


def page(theme, state):
    dark = theme == 'dark'
    chart, colours = chart_svg(theme)
    full = map_svg(theme, FULL_VIEW, label_lat=(5, 15, 25), label_lon=(115,))
    split = map_svg(theme, SPLIT_VIEW, label_lat=(20,), label_lon=(110, 115), px_per_unit=29.0)
    acc, warm = ('#74ABE2', '#D97757') if dark else ('#2C84DB', '#D97757')
    side = f'''<aside class="side">
    <div class="titlebar"><span class="lights"><i></i><i></i><i></i></span></div>
    <div class="sect">项目 {ICON['plus']}</div>
    <div class="item">{ICON['folder']}<span>South China Sea</span></div>
    <div class="item task{'' if state == 'welcome' else ' active'}"><span>三层环流的年代际转换</span><span class="spin"></span></div>
    <div class="item task"><span>南海表层叶绿素与 MODIS 的差异</span></div>
    <div class="item task"><span>2020 年次表层海洋热浪</span><span class="dot"></span></div>
    <div class="item">{ICON['folder']}<span>Gulf of Mexico</span></div>
    <div class="item task"><span>Loop Current 涡旋脱落</span></div>
    <div class="spacer"></div>
    <div class="foot"><span>{ICON['gear']}设置</span><span>{ICON['book']}审核</span></div>
  </aside>'''
    if state == 'web':
        side = f'''<aside class="side web">
    <div class="webbrand">{APP_ICON[theme]}<span>OceanX</span></div>
    <div class="sect">任务 {ICON['plus']}</div>
    <div class="item task active"><span>三层环流的年代际转换</span><span class="spin"></span></div>
    <div class="item task"><span>南海表层叶绿素与 MODIS 的差异</span></div>
    <div class="item task"><span>2020 年次表层海洋热浪</span><span class="dot"></span></div>
    <div class="spacer"></div>
    <div class="foot"><span>{ICON['gear']}设置</span></div>
  </aside>'''
    if state == 'result':
        result = f'''<div class="result open"><span class="ricon">{ICON['chart']}</span><span class="rt"><b>B1 · 三层涡度的时间序列</b><span>图 · 1993–2018 · 刚更新</span></span><span class="go">已在右侧打开</span></div>'''
        tail = '''<div class="act"><span class="check">✓</span><span>运行分析</span><span class="obj">· 计算三层区域积分涡度，7 年平滑</span><span class="time">3 分 05 秒</span><span class="details">详情 ›</span></div>'''
    else:
        result = f'''<div class="result"><span class="ricon">{ICON['chart']}</span><span class="rt"><b>B1 · 三层涡度的时间序列</b><span>图 · 1993–2018 · 刚更新</span></span><span class="go">在地图旁打开 ›</span></div>'''
        tail = '''<div class="act"><span class="run"><i></i></span><span>运行分析</span><span class="obj">· 计算中层底压力矩与涡管拉伸的趋势</span><span class="time">0 分 48 秒</span><span class="details">详情 ›</span></div>'''
    main = f'''<main class="main">
    <header class="top"><h1>三层环流的年代际转换</h1><div class="status"><span class="pulse"></span>运行中 · 6 分 12 秒</div><span class="more">{ICON['more']}</span></header>
    <div class="scroll"><div class="column"><div class="turn">
      <div class="user"><div class="bubble">用 1993–2022 年的 CMOMS 月平均场，复现 Zheng 等（2026）报告的南海三层环流在 2009 年前后的状态转换。</div></div>
      <div class="prose"><p>先读论文的方法：三层以 750 m 和 1500 m 分界，用 Stokes 定理把每层的区域积分涡度作为环流强度，两个时段分别是 1993–2008 和 2009–2018。</p></div>
      <div class="act"><span class="check">✓</span><span>读取文件</span><span class="obj">· zheng2026.pdf 的提取文本，第 2–3 页</span><span class="time">0 分 21 秒</span><span class="details">详情 ›</span></div>
      <div class="prose"><h3>上层和中层的趋势相反</h3><p>2009 年前上层气旋式环流每十年增强约 <b>6%</b>，中层反气旋式环流减弱；2009 年后两者反转，深层明显增强。与论文给出的方向一致，幅度还在核对。</p></div>
      {result}
      {tail}
    </div></div></div>
    <div class="composer-wrap"><div class="composer"><div class="ph">继续追问，或要求它核对某个量…</div><div class="crow"><span class="cbtn" title="添加 PDF 或数据文件夹">{ICON['add']}</span><span class="grow"></span><span class="cbtn">{ICON['mic']}</span><span class="send">{ICON['send']}</span></div></div></div>
  </main>'''
    if state == 'welcome':
        main = f'''<main class="main welcome-main">
    <div class="welcome">
      <div class="greet">{APP_ICON[theme]}<h2>你想用 OceanX 做什么？</h2></div>
      <div class="entries"><div class="entry">{ICON['papers']}<span>检索与阅读论文</span></div><div class="entry">{ICON['data']}<span>分析数据</span></div><div class="entry">{ICON['autoresearch']}<span>开展 Autoresearch</span></div></div>
      <div class="composer"><div class="ph">给这项研究起个名字</div><div class="crow"><span class="cbtn on">{ICON['add']}</span><span class="proj">{ICON['folder']}South China Sea</span><span class="grow"></span><span class="send">{ICON['send']}</span></div>
        <div class="menu"><div class="mi on">{ICON['pdf']}<span>添加 PDF</span></div><div class="mi">{ICON['folder_add']}<span>添加数据文件夹</span></div></div></div>
    </div>
    <div class="ack"><img src="data:image/png;base64,{CORE_LOGO}" alt="CORE · HKUST">感谢港澳海洋研究中心（CORE）支持</div>
  </main>'''
    keys = f'<div class="keys"><span><i style="background:{acc}"></i>上层环流</span><span><i style="background:{warm}"></i>黑潮入侵</span></div>'
    if state == 'result':
        mapcol = f'''<aside class="mapcol"><div class="mapcard">
      <div class="maparea">{split}
        <div class="chip tl">{ICON['layers']}南海<small>· 上层流场</small></div>
        <div class="attr">Natural Earth</div>
      </div>
      <div class="sheet"><div class="handle"><i></i></div>
        <div class="sheethead"><span class="kicker">图</span><b>B1 · 三层涡度的时间序列</b><span class="x">{ICON['expand']}{ICON['close']}</span></div>
        <div class="figure">{chart}
          <div class="figlegend"><span><i style="background:{colours[0]}"></i>上层</span><span><i style="background:{colours[1]}"></i>中层</span><span><i style="background:{colours[2]}"></i>深层</span></div>
          <p class="cap">区域积分涡度的标准化指数，7 年平滑；阴影为 2009 年后。示意数据。</p>
        </div>
      </div>
    </div></aside>'''
    elif state == 'welcome':
        mapcol = ''
    else:
        mapcol = f'''<aside class="mapcol"><div class="mapcard"><div class="maparea">{full}
      <div class="chip tl">{ICON['layers']}南海<small>· 上层流场 0–750 m</small></div>
      <div class="chip tr">{ICON['expand']}</div>
      <div class="zoom"><span>+</span><span>−</span></div>
      <div class="chip legend">{keys}</div>
      <div class="attr">Natural Earth</div>
    </div></div></aside>'''
    return f'''<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>OceanX mock</title><style>{CSS}</style></head>
<body class="{'dark' if dark else ''}"><div class="app{' nomap' if state == 'welcome' else ''}">{side}{main}{mapcol}</div></body></html>'''


(out / 'oceanx-light.html').write_text(page('light', 'running'), encoding='utf-8')
(out / 'oceanx-dark.html').write_text(page('dark', 'running'), encoding='utf-8')
(out / 'oceanx-result.html').write_text(page('light', 'result'), encoding='utf-8')
(out / 'oceanx-welcome.html').write_text(page('light', 'welcome'), encoding='utf-8')
(out / 'oceanx-welcome-dark.html').write_text(page('dark', 'welcome'), encoding='utf-8')
(out / 'oceanx-web.html').write_text(page('light', 'web'), encoding='utf-8')
print('pages written to', out)

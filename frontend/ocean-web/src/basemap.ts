import type {StyleSpecification} from 'maplibre-gl';
import landUrl from '../../ocean-desktop/src/renderer/assets/basemap/ne_110m_land.geojson?url';

const cartoKey = (import.meta.env.VITE_CARTO_BASEMAPS_API_KEY ?? '').trim();

/** Local geography remains below CARTO, and is used alone without a key. */
export const WEB_BASEMAP_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    land: {type: 'geojson', data: landUrl, attribution: 'Natural Earth (public domain)'},
    ...(cartoKey ? {'carto-light': {
      type: 'raster' as const,
      tiles: ['a', 'b', 'c', 'd'].map(subdomain =>
        `https://${subdomain}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png?key=${encodeURIComponent(cartoKey)}`),
      tileSize: 256,
      attribution: '© OpenStreetMap contributors © CARTO',
    }} : {}),
  },
  layers: [
    {id: 'ocean-background', type: 'background', paint: {'background-color': '#e8f2f6'}},
    {id: 'land', type: 'fill', source: 'land', paint: {'fill-color': '#f2f2ed'}},
    {id: 'coastline', type: 'line', source: 'land', paint: {'line-color': '#a8b9be', 'line-width': 0.8}},
    ...(cartoKey ? [{id: 'carto-light', type: 'raster' as const, source: 'carto-light', paint: {
      'raster-saturation': -.82, 'raster-contrast': -.08,
      'raster-brightness-min': .12, 'raster-brightness-max': .96,
    }}] : []),
  ],
};

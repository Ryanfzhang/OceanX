import type {StyleSpecification} from 'maplibre-gl';
import landUrl from './assets/basemap/ne_110m_land.geojson?url';

let configuredKey = '';

/** Both entry points supply their browser map key before mounting the workbench. */
export function configureBasemap(cartoKey: string): void {
  configuredKey = cartoKey.trim();
}

export function createBasemapStyle(cartoKey: string): StyleSpecification {
  const key = cartoKey.trim();
  return {
    version: 8,
    sources: {
      land: {type: 'geojson', data: landUrl, attribution: 'Natural Earth (public domain)'},
      ...(key ? {'carto-light': {
        type: 'raster' as const,
        tiles: ['a', 'b', 'c', 'd'].map(subdomain =>
          `https://${subdomain}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png?key=${encodeURIComponent(key)}`),
        tileSize: 256,
        attribution: '© OpenStreetMap contributors © CARTO',
      }} : {}),
    },
    layers: [
      {id: 'ocean-background', type: 'background', paint: {'background-color': '#e8f2f6'}},
      {id: 'land', type: 'fill', source: 'land', paint: {'fill-color': '#f2f2ed'}},
      {id: 'coastline', type: 'line', source: 'land', paint: {'line-color': '#a8b9be', 'line-width': 0.8}},
      ...(key ? [{id: 'carto-light', type: 'raster' as const, source: 'carto-light', paint: {
        'raster-saturation': -.82, 'raster-contrast': -.08,
        'raster-brightness-min': .12, 'raster-brightness-max': .96,
      }}] : []),
    ],
  };
}

export function getBasemapStyle(): StyleSpecification {
  return createBasemapStyle(configuredKey);
}

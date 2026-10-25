import type {StyleSpecification} from 'maplibre-gl';
import landUrl from './assets/basemap/ne_110m_land.geojson?url';

let configuredKey = '';

/** Both entry points supply their browser map key before mounting the workbench. */
export function configureBasemap(cartoKey: string): void {
  configuredKey = cartoKey.trim();
}

// A plain blue-grey sea and the interface's neutral land, in both themes.
const GEOGRAPHY = {
  light: {ocean: '#e3e9ef', land: '#f0eee6', coast: '#c9c5b9'},
  dark: {ocean: '#1d2024', land: '#30302e', coast: '#4a4944'},
};

function cartoTiles(key: string, dark: boolean): string[] {
  const style = dark ? 'dark_all' : 'light_all';
  return ['a', 'b', 'c', 'd'].map(subdomain =>
    `https://${subdomain}.basemaps.cartocdn.com/${style}/{z}/{x}/{y}@2x.png?key=${encodeURIComponent(key)}`);
}

export function createBasemapStyle(cartoKey: string): StyleSpecification {
  const key = cartoKey.trim();
  return {
    version: 8,
    sources: {
      land: {type: 'geojson', data: landUrl, attribution: 'Natural Earth (public domain)'},
      ...(key ? {'carto-light': {
        type: 'raster' as const,
        tiles: cartoTiles(key, false),
        tileSize: 256,
        attribution: '© OpenStreetMap contributors © CARTO',
      }} : {}),
    },
    layers: [
      {id: 'ocean-background', type: 'background', paint: {'background-color': GEOGRAPHY.light.ocean}},
      {id: 'land', type: 'fill', source: 'land', paint: {'fill-color': GEOGRAPHY.light.land}},
      {id: 'coastline', type: 'line', source: 'land', paint: {'line-color': GEOGRAPHY.light.coast, 'line-width': 0.8}},
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

type ThemedMap = {
  getLayer(id: string): unknown;
  getSource(id: string): unknown;
  setPaintProperty(layer: string, name: string, value: unknown): unknown;
};

/** Follow the app theme: dark geography, and CARTO's dark tiles when a key is configured. */
export function applyBasemapTheme(map: ThemedMap, dark: boolean): void {
  const colours = dark ? GEOGRAPHY.dark : GEOGRAPHY.light;
  if (map.getLayer('ocean-background')) map.setPaintProperty('ocean-background', 'background-color', colours.ocean);
  if (map.getLayer('land')) map.setPaintProperty('land', 'fill-color', colours.land);
  if (map.getLayer('coastline')) map.setPaintProperty('coastline', 'line-color', colours.coast);
  const carto = map.getSource('carto-light') as {setTiles?: (tiles: string[]) => unknown} | undefined;
  if (configuredKey && carto?.setTiles) carto.setTiles(cartoTiles(configuredKey, dark));
}

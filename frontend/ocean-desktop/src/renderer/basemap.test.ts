import {describe, expect, it} from 'vitest';
import {configureBasemap, createBasemapStyle, getBasemapStyle} from './basemap.js';
import {desktopMapConfig} from '../shared/map-config.js';

describe('runtime map configuration', () => {
  it('uses bundled geography when no map key is configured', () => {
    const style = createBasemapStyle('');
    expect(style.sources.land.type).toBe('geojson');
    expect(style.sources['carto-light']).toBeUndefined();
    expect(style.layers.map(layer => layer.id)).toContain('coastline');
  });

  it('changes the map at runtime with an encoded browser key', () => {
    configureBasemap(' first+key ');
    const first = getBasemapStyle().sources['carto-light'];
    expect(first.type).toBe('raster');
    if (first.type !== 'raster') throw new Error('Expected raster');
    expect(first.tiles?.[0]).toContain('?key=first%2Bkey');
    configureBasemap('second');
    const second = getBasemapStyle().sources['carto-light'];
    if (second.type !== 'raster') throw new Error('Expected raster');
    expect(second.tiles?.[0]).toContain('?key=second');
    expect(second.attribution).toContain('CARTO');
    configureBasemap('');
    expect(getBasemapStyle().sources['carto-light']).toBeUndefined();
  });

  it('exposes only the browser map key and ignores legacy build settings', () => {
    expect(desktopMapConfig({OCEAN_DESKTOP_CARTO_API_KEY: ' browser-key ',
      DEEPSEEK_API_KEY: 'private-model-key', VITE_CARTO_BASEMAPS_API_KEY: 'old'}))
      .toEqual({cartoKey: 'browser-key'});
    expect(desktopMapConfig({VITE_CARTO_BASEMAPS_API_KEY: 'old'})).toEqual({cartoKey: ''});
  });
});

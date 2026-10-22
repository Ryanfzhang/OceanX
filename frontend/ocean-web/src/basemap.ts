import type {StyleSpecification} from 'maplibre-gl';
import landUrl from '../../ocean-desktop/src/renderer/assets/basemap/ne_110m_land.geojson?url';

/** Reuse bundled public-domain geography: no tile API, API key or network. */
export const WEB_BASEMAP_STYLE: StyleSpecification = {
  version: 8,
  sources: {land: {type: 'geojson', data: landUrl, attribution: 'Natural Earth (public domain)'}},
  layers: [
    {id: 'ocean-background', type: 'background', paint: {'background-color': '#e8f2f6'}},
    {id: 'land', type: 'fill', source: 'land', paint: {'fill-color': '#f2f2ed'}},
    {id: 'coastline', type: 'line', source: 'land', paint: {'line-color': '#a8b9be', 'line-width': 0.8}},
  ],
};

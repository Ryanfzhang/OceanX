import type {MapConfig} from './bridge.js';

export function desktopMapConfig(environment: Record<string, string | undefined>): MapConfig {
  return {cartoKey: (environment.OCEAN_DESKTOP_CARTO_API_KEY ?? '').trim()};
}

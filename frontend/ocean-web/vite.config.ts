import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import {fileURLToPath} from 'node:url';
import {dirname, resolve} from 'node:path';
import {readFileSync} from 'node:fs';

const here = dirname(fileURLToPath(import.meta.url));
const renderer = resolve(here, '../ocean-desktop/src/renderer');
const dependencies = Object.keys(JSON.parse(readFileSync(resolve(here, 'package.json'), 'utf8')).dependencies);

export default defineConfig({
  root: here,
  base: './',
  resolve: {
    alias: [
      {find: '@desktop-renderer', replacement: renderer},
      ...dependencies.map((name) => ({find: name, replacement: resolve(here, 'node_modules', name)})),
    ],
    dedupe: ['react', 'react-dom', 'react/jsx-runtime'],
  },
  plugins: [
    {
      name: 'web-resource-addresses',
      resolveId(source, importer) {
        if (!importer?.startsWith(renderer)) return;
        const overrides: Record<string, string> = {
          'ProjectTaskSidebar.js': 'TaskSidebar.tsx',
          'OceanXWelcome.js': 'Welcome.tsx',
          'DesktopSettingsDialog.js': 'SettingsDialog.tsx',
          'ResearchLibraryDialog.js': 'NoResearchLibrary.tsx',
        };
        const name = source.split('/').at(-1)!;
        if (overrides[name]) return resolve(here, 'src', overrides[name]);
      },
      enforce: 'pre',
      transform(code, id) {
        // Adapt the web bundle only; never edit the shared Desktop source files.
        if (id.startsWith(renderer) && /\.[tj]sx?(\?|$)/.test(id)) {
          return code.replaceAll('ocean-artifact://resource/', '/api/resources/')
            // MapLibre's current browser package exposes named exports. Desktop
            // keeps its own pinned dependency and original import unchanged.
            .replace(
              "import maplibregl, {type Map as MapLibreMap} from 'maplibre-gl';",
              "import * as maplibregl from 'maplibre-gl'; import type {Map as MapLibreMap} from 'maplibre-gl';",
            );
        }
      },
    },
    react(),
  ],
  build: {outDir: 'dist', emptyOutDir: true},
});

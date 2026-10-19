import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import {dirname} from 'node:path';
import {fileURLToPath} from 'node:url';

const desktopRoot = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  base: './',
  root: 'src/renderer',
  envDir: desktopRoot,
  plugins: [react()],
  build: {
    outDir: '../../dist/renderer',
    emptyOutDir: true,
    rolldownOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('/node_modules/maplibre-gl/')) return 'maplibre';
          if (id.includes('/node_modules/uplot/')) return 'uplot';
          if (id.includes('/node_modules/react/') || id.includes('/node_modules/react-dom/')) return 'react';
          return undefined;
        },
      },
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5177,
  },
});

import {setWorkerUrl} from 'maplibre-gl';
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import {installWebBridge} from './bridge.js';
import './web.css';

setWorkerUrl(mapWorkerUrl);

try {
  await installWebBridge();
  // Reuse the real workbench, figures and protocol client without changing Desktop.
  // @ts-expect-error Vite resolves the existing TSX entry, which has no module exports.
  await import('@desktop-renderer/main.tsx');
} catch (error) {
  const root = document.getElementById('root')!;
  const message = document.createElement('p');
  message.textContent = error instanceof Error ? error.message : 'Server connection unavailable.';
  root.append(message);
}

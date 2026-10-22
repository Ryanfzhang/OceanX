import {createRoot} from 'react-dom/client';
import 'katex/dist/katex.min.css';
import 'maplibre-gl/dist/maplibre-gl.css';
import {App} from './App.js';
import {UiLanguageProvider} from './i18n.js';
import {configureBasemap} from './basemap.js';
import './styles.css';

async function mount(): Promise<void> {
  try {
    const map = await window.oceanDesktop.getMapConfig();
    configureBasemap(map.cartoKey);
  } catch {
    // Geography is bundled locally; a missing map key must not block tasks.
    configureBasemap('');
  }
  createRoot(document.getElementById('root')!).render(<UiLanguageProvider><App /></UiLanguageProvider>);
}
void mount();

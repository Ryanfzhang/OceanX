// Renders oceanx-icon.svg into the PNG sizes of a macOS iconset with headless Chrome.
// Usage: node export_icons.mjs <oceanx-icon.svg> <output .iconset folder>
// (run with frontend/ocean-desktop/node_modules on NODE_PATH, or from a folder that links it)
import {mkdir, readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {chromium} from 'playwright';

const [svgPath, iconset] = process.argv.slice(2);
const svg = await readFile(svgPath, 'utf8');
await mkdir(iconset, {recursive: true});
const browser = await chromium.launch({channel: 'chrome', headless: true});
for (const size of [16, 32, 128, 256, 512]) {
  for (const scale of [1, 2]) {
    const page = await browser.newPage({viewport: {width: size, height: size}, deviceScaleFactor: scale});
    await page.setContent(`<style>html,body{margin:0;background:transparent}svg{display:block;width:${size}px;height:${size}px}</style>${svg}`);
    const name = scale === 1 ? `icon_${size}x${size}.png` : `icon_${size}x${size}@2x.png`;
    await page.screenshot({path: join(iconset, name), omitBackground: true});
    await page.close();
  }
}
await browser.close();

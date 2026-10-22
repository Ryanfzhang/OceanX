import {afterEach, describe, expect, it} from 'vitest';
import {mkdtempSync, mkdirSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join} from 'node:path';
import {frontendIsCurrent, recordFrontendBuild} from '../../scripts/frontend-build-cache.mjs';

const temporary: string[] = [];
function fixture(): string {
  const root = mkdtempSync(join(tmpdir(), 'oceanx-build-')); temporary.push(root);
  for (const file of ['src/main.ts', 'dist/renderer/index.html', 'dist/renderer/assets/main.js',
    'dist-electron/main.js', 'dist-electron/preload.cjs']) {
    mkdirSync(dirname(join(root, file)), {recursive: true}); writeFileSync(join(root, file), 'initial');
  }
  return root;
}
afterEach(() => {temporary.splice(0).forEach(path => rmSync(path, {recursive: true, force: true}));});

describe('frontend build cache', () => {
  it('does not rebuild for model or map config changes', () => {
    const root = fixture();
    expect(frontendIsCurrent(root)).toBe(false);
    recordFrontendBuild(root); expect(frontendIsCurrent(root)).toBe(true);
    writeFileSync(join(root, 'desktop.toml'), '[map]\ncarto_api_key="changed"');
    expect(frontendIsCurrent(root)).toBe(true);
  });
  it('rebuilds for source/dependency changes and damaged outputs', () => {
    const root = fixture(); recordFrontendBuild(root);
    writeFileSync(join(root, 'src/main.ts'), 'changed'); expect(frontendIsCurrent(root)).toBe(false);
    recordFrontendBuild(root);
    writeFileSync(join(root, 'package-lock.json'), 'changed'); expect(frontendIsCurrent(root)).toBe(false);
    recordFrontendBuild(root);
    writeFileSync(join(root, 'dist/renderer/assets/main.js'), 'damaged'); expect(frontendIsCurrent(root)).toBe(false);
    recordFrontendBuild(root);
    rmSync(join(root, 'dist-electron/preload.cjs')); expect(frontendIsCurrent(root)).toBe(false);
  });
});

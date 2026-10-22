import {createHash} from 'node:crypto';
import {existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync} from 'node:fs';
import {dirname, join} from 'node:path';

const inputs = ['src', 'package.json', 'package-lock.json', 'tsconfig.json', 'tsconfig.main.json',
  'vite.config.ts', 'scripts/build-preload.mjs', 'scripts/ensure-frontend.mjs', 'scripts/frontend-build-cache.mjs'];
const outputs = ['dist/renderer', 'dist-electron'];
const required = ['dist/renderer/index.html', 'dist-electron/main.js', 'dist-electron/preload.cjs'];
const stamp = 'dist/frontend-build.json';

function digest(root, paths) {
  const hash = createHash('sha256');
  const visit = relative => {
    const path = join(root, relative);
    if (!existsSync(path)) {hash.update(`missing:${relative}\0`); return;}
    if (statSync(path).isDirectory()) {
      for (const name of readdirSync(path).sort()) {
        if (name !== '.DS_Store') visit(join(relative, name));
      }
    } else {
      const contents = readFileSync(path);
      hash.update(`${relative}\0${contents.length}\0`); hash.update(contents);
    }
  };
  paths.forEach(visit);
  return hash.digest('hex');
}

export function frontendInputs(root) {
  return createHash('sha256').update(JSON.stringify({
    source: digest(root, inputs), node: process.versions.node, platform: process.platform, arch: process.arch,
  })).digest('hex');
}

export function frontendIsCurrent(root) {
  try {
    if (!required.every(path => existsSync(join(root, path)))) return false;
    const saved = JSON.parse(readFileSync(join(root, stamp), 'utf8'));
    return saved.inputs === frontendInputs(root) && saved.outputs === digest(root, outputs);
  } catch {return false;}
}

export function recordFrontendBuild(root) {
  if (!required.every(path => existsSync(join(root, path)))) throw new Error('Frontend build output is incomplete.');
  const path = join(root, stamp);
  mkdirSync(dirname(path), {recursive: true});
  writeFileSync(path, JSON.stringify({inputs: frontendInputs(root), outputs: digest(root, outputs)}) + '\n');
}

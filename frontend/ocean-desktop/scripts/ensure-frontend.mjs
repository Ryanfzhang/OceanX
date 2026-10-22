import {spawnSync} from 'node:child_process';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {frontendIsCurrent, recordFrontendBuild} from './frontend-build-cache.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
if (!frontendIsCurrent(root)) {
  const result = spawnSync(process.platform === 'win32' ? 'npm.cmd' : 'npm', ['run', 'build'], {
    cwd: root, env: process.env, stdio: 'inherit',
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
  recordFrontendBuild(root);
}

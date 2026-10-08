"""Fetch only new output figures; unchanged figures reuse the historical bundle."""
import hashlib
import io
import json
import shlex
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OLD = ROOT.parent / '2026-10-08-three-methods'
WORK = Path('/Users/ryanzhang/.codex/visualizations/2026/08/22/01a02889-8101-7d21-9d67-f7b62e1a6809/benchmark-review-20261008-r2')
HISTORICAL = WORK.parent / 'benchmark-review'


def main():
    changes = json.loads((ROOT / 'selection.json').read_text())['changes']
    keys = {(c['query'], c['method']) for c in changes}
    manifest = []
    for i in json.loads((OLD / 'figure-manifest.json').read_text()):
        if (i['query'], i['method']) not in keys:
            manifest.append({**i, 'target': i['target'] if i['target'].startswith('../') else '../2026-10-08-three-methods/' + i['target'],
                             'reused_from': i.get('reused_from', '2026-10-08-three-methods')})
    fresh = []
    for q, method in sorted(keys):
        run = json.loads((WORK / (q + '.json')).read_text())['methods'][method]
        seen = set()
        for image in run['images']:
            rel = Path(image['path'])
            if 'scratch' in rel.parts or image['sha256'] in seen:
                continue
            seen.add(image['sha256'])
            fresh.append({'query': q, 'method': method,
                          'source': str(Path(run['attempt']) / rel),
                          'relative_source': str(rel),
                          'target': f'assets/{q}/{method}/{len(seen):02d}-{rel.name}',
                          'sha256': image['sha256'], 'bytes': image['bytes']})
    remote = '''import json,sys,tarfile
from pathlib import Path
items=json.load(sys.stdin)
base=Path('/import/home3/share/oceanx-bench').resolve()
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as t:
 for i in items:
  p=Path(i['source'])
  if p.is_symlink() or not p.resolve().is_relative_to(base) or not p.is_file():
   raise ValueError('Invalid read-only source')
  t.add(p,arcname=i['target'],recursive=False)
'''
    command = '/home/mafzhang/miniconda3/envs/oceanx-bench/bin/python -c ' + shlex.quote(remote)
    proc = subprocess.run(['ssh', 'macyang10.math.ust.hk', command],
                          input=json.dumps(fresh).encode(), capture_output=True, check=True)
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as archive:
        for member in archive.getmembers():
            target = ROOT / member.name
            if not member.isfile() or not target.resolve().is_relative_to((ROOT / 'assets').resolve()):
                raise ValueError('Unsafe archive member')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
    manifest.extend(fresh)
    for i in manifest:
        file = ROOT / i['target']
        assert file.stat().st_size == i['bytes'], i['target']
        assert hashlib.sha256(file.read_bytes()).hexdigest() == i['sha256'], i['target']
    (ROOT / 'figure-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(f'{len(fresh)} new figures downloaded; {len(manifest)-len(fresh)} unchanged figures reused; all SHA-256 checked')


if __name__ == '__main__':
    main()

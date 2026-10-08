"""Refresh the bilingual artifact review; original runs remain read-only.

The old review is an immutable historical reading. Select the latest terminal
attempt, not the highest score, and independently review only changed evidence.
"""
import ast
import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
OLD = Path('/Users/ryanzhang/.codex/visualizations/2026/08/22/01a02889-8101-7d21-9d67-f7b62e1a6809/benchmark-review')
PREVIOUS = HERE.parent / '2026-10-08-three-methods'
WORK = OLD.parent / 'benchmark-review-20261008-r2'
PYTHON = '/home/mafzhang/miniconda3/envs/oceanx-bench/bin/python'
HOST = 'macyang10.math.ust.hk'


def collect():
    original = json.loads((OLD.parent / 'benchmark-review-20261008/evidence.json').read_text())
    prior = {m: {q: {'attempt': a['attempt'],
                     'answer_sha256': hashlib.sha256(a['answer'].encode()).hexdigest()}
                 for q, a in d['queries'].items()}
             for m, d in original['methods'].items()}
    module = ast.parse((OLD / 'collect.py').read_text())
    remote = next(ast.literal_eval(n.value) for n in module.body
                  if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'REMOTE'
                                                      for t in n.targets))
    remote = remote.replace("bundle={'methods':{},'rubrics':{},'tasks':{}}",
                            "prior=" + repr(prior) + "\n"
                            "inventory=[]\n"
                            "bundle={'methods':{},'rubrics':{},'tasks':{}}")
    remote = remote.replace(
        "        if len(ats)!=1: raise ValueError('Expected one attempt, found '+str(case))\n"
        "        at=ats[0]; result=json.loads((at/'result.json').read_text())",
        "        terminal=[a for a in ats if (a/'result.json').is_file()]\n"
        "        if not terminal: raise ValueError('No terminal attempt: '+str(case))\n"
        "        at=terminal[-1]; result=json.loads((at/'result.json').read_text())\n"
        "        ans=(at/'answer.md').read_bytes() if (at/'answer.md').is_file() else b''\n"
        "        digest=hashlib.sha256(ans).hexdigest()\n"
        "        inventory.append({'query':case.name,'method':method,'selected':str(at),\n"
        "                          'attempts':[str(a) for a in ats],\n"
        "                          'status':result.get('status'),'answer_sha256':digest})\n"
        "        old=prior[method].get(case.name)\n"
        "        if old and old['attempt']==str(at) and old['answer_sha256']==digest: continue")
    remote = remote.replace("print(json.dumps(bundle,ensure_ascii=False))",
                            "bundle['selection_inventory']=inventory\nprint(json.dumps(bundle,ensure_ascii=False))")
    proc = subprocess.run(['ssh', HOST, PYTHON + ' -'], input=remote,
                          text=True, capture_output=True, check=True)
    new = json.loads(proc.stdout)
    changed = []
    for m, d in new['methods'].items():
        original['methods'][m]['current_arm'] = d['arm']
        for q, a in d['queries'].items():
            old = original['methods'][m]['queries'][q]
            changed.append({'query': q, 'method': m, 'old_attempt': old['attempt'],
                            'new_attempt': a['attempt'], 'old_status': old['result']['status'],
                            'new_status': a['result']['status'],
                            'old_answer_sha256': hashlib.sha256(old['answer'].encode()).hexdigest(),
                            'new_answer_sha256': hashlib.sha256(a['answer'].encode()).hexdigest()})
            assert new['rubrics'][q] == original['rubrics'][q], 'Rubric changed: ' + q
            original['methods'][m]['queries'][q] = a
    original['selection_inventory'] = new['selection_inventory']
    original['changed_attempts'] = changed
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / 'evidence.json').write_text(json.dumps(original, ensure_ascii=False))
    (HERE / 'selection.json').write_text(json.dumps({'rule': 'latest terminal attempt, never best score',
                                                   'changes': changed,
                                                   'inventory': new['selection_inventory']},
                                                  ensure_ascii=False, indent=2) + '\n')
    for q in original['rubrics']:
        case = {'rubric': original['rubrics'][q], 'task': original['tasks'][q],
                'methods': {m: d['queries'][q] for m, d in original['methods'].items()}}
        (WORK / (q + '.json')).write_text(json.dumps(case, ensure_ascii=False))
    print('Changed attempts:', len(changed))
    for c in changed:
        print(c['query'], c['method'], c['old_status'], '->', c['new_status'], c['new_attempt'])


if __name__ == '__main__':
    collect()

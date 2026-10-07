"""Read-only run audit for the 51 attempts already reviewed on 2026-10-06.

Writes only the caller's local output directory. Never imports OceanX storage.
"""
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SNAPSHOT = Path('/Users/ryanzhang/.codex/visualizations/2026/08/22/01a02889-8101-7d21-9d67-f7b62e1a6809/benchmark-review')
REMOTE = r'''
import json, sqlite3, hashlib, re, collections
from pathlib import Path
from datetime import datetime, timezone

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
def plain(s):
    # Some kernel records store escaped presentation text, not actual newlines.
    s=str(s or '').replace('\\n','\n').replace('\\r','\r')
    s=re.sub(r'\\u001[bB]|\\x1[bB]', '\x1b', s)
    return re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '',s)
def signature(s):
    lines=[x for x in plain(s).splitlines() if x.strip()]
    return ' '.join(lines[-1].split()) if lines else None
def content_text(c):
    if isinstance(c,str): return c
    if isinstance(c,list): return '\n'.join(x.get('text','') for x in c if isinstance(x,dict))
    return ''
def nb_errors(markdown):
    # Only output blocks, never exception strings in source code or commentary.
    errors=[]
    for match in re.finditer(r'### Output (\d+):\s*```[^\n]*\n(.*?)\n```',markdown,re.S):
        body=plain(match.group(2))
        if 'Traceback' in body or re.search(r'^\w*(?:Error|Exception|Interrupt):',body,re.M):
            # Markdown combines error and later stdout from one cell. The last
            # exception line is the error's last line, not subsequent print output.
            ends=re.findall(r'^(?:[\w.]+)?(?:Error|Exception|Interrupt):[^\n]*',body,re.M)
            errors.append({'output_index':int(match.group(1)), 'last_line':signature(ends[-1]) if ends else None})
    return errors
def repeat_stats(rows):
    prior={}; repeats=[]; ambiguous=0
    for r in rows:
        agent=r['agent']; old=prior.get(agent)
        if r['failed'] and r.get('signature') and old and old['failed'] and old.get('signature')==r['signature']:
            repeats.append({'previous':old['id'],'current':r['id'],'agent':agent,'signature':r['signature']})
        elif r['failed'] and old and old['failed'] and (not r.get('signature') or not old.get('signature')):
            ambiguous+=1
        prior[agent]=r
    return {'executions':len(rows),'failures':sum(r['failed'] for r in rows),
            'unknown_failure_signatures':sum(r['failed'] and not r.get('signature') for r in rows),
            'repeated_failures':len(repeats), 'ambiguous_pairs':ambiguous, 'pairs':repeats,
            'score':100*(1-len(repeats)/len(rows)) if rows else 0,
            'score_lower':100*(1-(len(repeats)+ambiguous)/len(rows)) if rows else 0}

paths=json.loads(input())
out={'collected_at_utc':datetime.now(timezone.utc).isoformat(),'attempts':[]}
for spec in paths:
    a=Path(spec['attempt']); method=spec['method']; qid=spec['query']; result=json.loads((a/'result.json').read_text())
    ans=a/'answer.md'; rows=[]; files=[a/'result.json']; notes=[]; finch_meta={}
    if method=='OceanX':
        db=a/'state/workspace.sqlite3'; files.append(db)
        con=sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True)
        for row in con.execute('select execution_id,agent_thread_id,state,started_at,request_json,result_json from code_executions order by started_at,execution_id'):
            eid,agent,state,started,req,res=row; res=json.loads(res or '{}'); req=json.loads(req)
            failed=state in ('failed','timed_out','cancelled') or bool(res.get('returncode'))
            if state in ('running','pending'): notes.append('Nonterminal execution '+eid); continue
            err=res.get('stderr') or ''
            if failed and not err:
                p=Path((res.get('logs') or {}).get('stderr') or '/nonexistent')
                if p.is_file() and p.resolve().is_relative_to(a.resolve()):err=p.read_text(errors='replace')
            if failed and not err:err=res.get('stdout') or res.get('error') or res.get('limit_trigger') or ''
            rows.append({'id':eid,'agent':agent,'state':state,'started_at':started,'failed':failed,
                         'signature':signature(err) if failed else None})
        led=[]
        for (raw,) in con.execute('select record_json from model_call_observations'):
            rec=json.loads(raw);usage=rec.get('usage') or {};led.append(usage)
        ledger={'calls':len(led),'input_tokens':sum(x.get('input_tokens') or 0 for x in led),
                'output_tokens':sum(x.get('output_tokens') or 0 for x in led)}
        con.close()
    elif method=='Claude':
        p=a/'events.jsonl';files.append(p); tool_names={}; seen=set();unknown=[]
        for line_no,line in enumerate(p.open(),1):
            d=json.loads(line); message=d.get('message')
            bs=message.get('content',[]) if isinstance(message,dict) else []
            if not isinstance(bs,list): continue
            for b in bs:
                if not isinstance(b,dict):continue
                if b.get('type')=='tool_use':tool_names[b['id']]=b.get('name')
                if b.get('type')!='tool_result':continue
                tid=b.get('tool_use_id'); name=tool_names.get(tid)
                if not name:unknown.append(tid)
                if name not in ('Bash','bash','Python','python','execute','run_code'):continue
                if tid in seen:continue
                seen.add(tid);failed=bool(b.get('is_error'))
                text=content_text(b.get('content'))
                rows.append({'id':tid,'agent':d.get('session_id') or 'claude','state':'failed' if failed else 'succeeded',
                             'failed':failed,'signature':signature(text) if failed else None,
                             'tool':name,'line':line_no})
        if unknown:notes.append('Unmatched tool result IDs: '+str(len(unknown)))
        ledger=None
    else:
        p=a/'code_runs.jsonl'; rows_raw=[]
        if p.exists():
            files.append(p)
            seen=set()
            for line_no,line in enumerate(p.open(),1):
                d=json.loads(line)
                if d.get('state')=='running':continue
                if d['execution_id'] in seen:raise ValueError('Duplicate terminal execution')
                seen.add(d['execution_id']);d['line']=line_no;rows_raw.append(d)
        # Observations at step n show execution after action n-1; final action has
        # no later observation. Its exact error is recovered from saved notebook.
        tp=a/'transcript.jsonl';snapshots=[];last_action=None
        if tp.exists():
            files.append(tp)
            for line in tp.open():
                d=json.loads(line)
                if d.get('type')=='action':last_action=d
                if d.get('type')!='observations':continue
                ms=d.get('messages') or []; tools=[m for m in ms if m.get('role')=='tool' and m.get('name')=='edit_cell']
                if not tools:continue
                texts=[content_text(m.get('content')) for m in ms if m.get('role')=='user']
                markdown=next((x for x in texts if 'Markdown representation of notebook' in x),'')
                if not markdown:continue
                errors=nb_errors(markdown)
                # A rejected edit without a notebook run must not consume a row.
                accepted=[t for t in tools if str(t.get('content','')).startswith(('Appended','Edited'))]
                if accepted:
                    # Only the last replay in a multi-edit action has a saved
                    # observation. Do not assign its errors to earlier replays.
                    snapshots.extend([None]*(len(accepted)-1))
                    snapshots.append({'step':d['step']-1,'errors':errors})
        final=a/'workspace/notebook.ipynb'
        final_err=[]
        if final.exists():
            nb=json.loads(final.read_text());files.append(final)
            for i,c in enumerate(nb.get('cells',[])):
                for o in c.get('outputs',[]):
                    if o.get('output_type')=='error':
                        sig=signature('\n'.join(o.get('traceback') or [])) or signature(str(o.get('ename'))+': '+str(o.get('evalue')))
                        final_err.append({'output_index':i,'last_line':sig})
        if len(snapshots)+1==len(rows_raw):
            snapshots.append({'step':last_action.get('step') if last_action else None,'errors':final_err,'source':'final_notebook'})
        finch_meta={'terminal_runs':len(rows_raw),'execution_snapshots':len(snapshots),
                    'alignment_valid':len(snapshots)==len(rows_raw),'persistent_error_cell_pairs':0,'last_line_repeats_from_class_only':0}
        for i,r in enumerate(rows_raw):
            failed=r['state']!='succeeded'; snap=snapshots[i] if finch_meta['alignment_valid'] else None
            err=snap['errors'] if snap else []
            # Validate snapshot errors against the ledger's exception-name list.
            classes=[x['last_line'].split(':',1)[0] for x in err if x.get('last_line')]
            if snap and r.get('errors',[])!=classes:
                notes.append('Finch signature alignment mismatch at '+r['execution_id'])
                err=[];snap=None
            sig=signature(r.get('error')) if failed and r.get('error') else (err[-1]['last_line'] if err else None)
            rows.append({'id':r['execution_id'],'agent':'finch','state':r['state'],'failed':failed,
                         'signature':sig if failed else None,'errors':err,'error_classes':r.get('errors',[]),
                         'step':snap['step'] if snap else None,'line':r['line']})
            if i and failed and rows[-2]['failed']:
                before={(x['output_index'],x['last_line']) for x in rows[-2].get('errors',[])}
                same=before & {(x['output_index'],x['last_line']) for x in err}
                finch_meta['persistent_error_cell_pairs']+=len(same)
                if r.get('errors') and r.get('errors')==rows_raw[i-1].get('errors'):
                    finch_meta['last_line_repeats_from_class_only']+=1
        if rows_raw and not finch_meta['alignment_valid']:notes.append('Cannot align Finch executions and notebook snapshots')
        ledger=None
    stats=repeat_stats(rows)
    out['attempts'].append({'query':qid,'method':method,'attempt':str(a),
        'status':result['status'],'answer_bytes':ans.stat().st_size if ans.exists() else 0,
        'answer_sha256':digest(ans),'result_sha256':digest(a/'result.json'),
        'delivery':100 if result['status']=='completed' and ans.exists() and ans.read_text().strip() else 0,
        'elapsed_seconds':result.get('elapsed_seconds'),'result_cost':{k:result.get(k) for k in ('external_usage','whole_call_tokens','coordinator_usage','expert_usage')},
        'ledger_supplement':ledger,'execution_stats':stats,'execution_rows':rows,
        'finch':finch_meta,'notes':notes,'sources':[str(p) for p in files]})
print(json.dumps(out,ensure_ascii=False))
'''


def main():
    evidence = json.loads((SNAPSHOT / 'evidence.json').read_text())
    paths = [{'method': m, 'query': q, 'attempt': a['attempt']}
             for m, d in evidence['methods'].items() for q, a in d['queries'].items()]
    # stdin first line supplies the fixed attempt IDs; the rest is executable code.
    payload = 'import sys\n' + REMOTE.replace('paths=json.loads(input())',
                                            'paths='+repr(paths))
    result = subprocess.run(['ssh', 'macyang10.math.ust.hk',
        '/home/mafzhang/miniconda3/envs/oceanx-bench/bin/python -'],
        input=payload,text=True,capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-6000:])
    audit=json.loads(result.stdout)
    for a in audit['attempts']:
        old=evidence['methods'][a['method']]['queries'][a['query']]
        expected=__import__('hashlib').sha256(old['answer'].encode()).hexdigest()
        assert a['answer_sha256']==expected or (not old['answer'] and not a['answer_bytes']), (a['query'],a['method'],'answer changed')
    (HERE/'run-measures.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
    for m in evidence['methods']:
        rows=[a for a in audit['attempts'] if a['method']==m]
        print(m,'attempts',len(rows),'executions',sum(a['execution_stats']['executions'] for a in rows),
              'repeats',sum(a['execution_stats']['repeated_failures'] for a in rows),
              'unknown errors',sum(a['execution_stats']['unknown_failure_signatures'] for a in rows))
    for a in audit['attempts']:
        if a['notes']:print(a['query'],a['method'],a['notes'])


if __name__=='__main__':
    main()

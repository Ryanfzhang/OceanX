"""Compute six-axis trial tables without changing any original rubric scores."""
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean

from count_annotations import OPEN, PAPER

HERE=Path(__file__).resolve().parent
SNAPSHOT=Path('/Users/ryanzhang/.codex/visualizations/2026/08/22/01a02889-8101-7d21-9d67-f7b62e1a6809/benchmark-review')
METHODS=('OceanX','Claude','Finch')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources(attempt):
    yield 'answer.md',attempt['answer']
    for k,v in attempt['texts'].items():
        if k.endswith('.md'):
            yield k,v
    for path,nb in attempt['notebooks'].items():
        for c in nb['cells']:
            if c['execution_count'] is not None:
                yield path+'#cell-'+str(c['index']),c['source']+'\n'+json.dumps(c['outputs'],ensure_ascii=False)
    # Code is used only to locate an already-reviewed executed experiment whose
    # result is saved elsewhere in this snapshot; not a proposed pipeline.
    for k,v in attempt['texts'].items():
        if k.endswith(('.py','.csv','.json')):
            yield k,v


def locate(attempt,pattern):
    for path,text in sources(attempt):
        match=re.search(pattern,text,re.I|re.S)
        if match:
            start=max(0,text.rfind('\n',0,match.start())+1)
            end=text.find('\n',match.end())
            end=len(text) if end<0 else end
            return {'source':str(Path(attempt['attempt'])/path.split('#',1)[0]),
                    'fragment':path.split('#',1)[1] if '#' in path else None,
                    'line':text[:match.start()].count('\n')+1,
                    'quote':text[start:end][:1000], 'locator':pattern}
    raise ValueError('Evidence locator absent: '+pattern)


def component(judged=None,counted=None,run=None,run_low=None):
    # Missing kind reallocates its weight to J. Run-only robustness is the mean
    # of delivery and repetition, not a 0.25-weighted score against phantom J.
    if judged is None:
        assert counted is None and run is not None
        return {'judged':None,'counted':None,'run':run,'run_lower':run_low,
                'combined':run,'combined_lower':run_low if run_low is not None else run}
    jw=.5+(.25 if counted is None else 0)+(.25 if run is None else 0)
    value=jw*judged+(.25*counted if counted is not None else 0)+(.25*run if run is not None else 0)
    low=jw*judged+(.25*counted if counted is not None else 0)+(.25*(run_low if run_low is not None else run) if run is not None else 0)
    return {'judged':judged,'counted':counted,'run':run,'run_lower':run_low,
            'combined':value,'combined_lower':low}


def judged(criteria,letters):
    cs=[c for c in criteria if c['id'].rsplit('-',1)[-1] in letters]
    return 100*sum(c['weight']*c['level']/4 for c in cs)/sum(c['weight'] for c in cs)


def per_attempt(q,m,evidence,score,run):
    rubric=evidence['rubrics'][q]; attempt=evidence['methods'][m]['queries'][q]
    criteria=score['criteria'];stats=run['execution_stats']
    robust=(run['delivery']+stats['score'])/2
    robust_low=(run['delivery']+stats['score_lower'])/2
    out={'query':q,'method':m,'type':rubric['type'],'status':run['status'],
         'attempt':attempt['attempt'],'original_primary_score':score['score'],
         'original_criterion_total':sum(c['weight']*c['level']/4 for c in criteria),
         'original_criteria':criteria,'delivery':run['delivery'],
         'repeated_failure':stats,'run_part':robust,'run_part_lower':robust_low,
         'elapsed_seconds':run['elapsed_seconds'],'original_recorded_tokens':score.get('tokens'),
         'original_recorded_model_calls':score.get('calls'), 'counts':{}}
    if rubric['type']=='open_problem':
        a=OPEN[q][m];out['count_notes']=a['note']
        for group,key in [('depth','depth_probes'),('breadth','breadth_probes')]:
            entries=[]
            for i,probe in enumerate(rubric[key],1):
                entries.append({'index':i,'probe':probe,'addressed':i in a[group],
                                'evidence':locate(attempt,a[group][i]) if i in a[group] else None})
            out['counts'][group]=entries
        causes=[]
        for c in rubric.get('candidate_causes',[]):
            cid=c['id']; causes.append({'id':cid,'cause':c['cause'],'listed_test':c['test'],
                                       'tested':cid in a['causes'], 'matches_reference':None,
                                       'evidence':locate(attempt,a['causes'][cid]) if cid in a['causes'] else None})
        out['counts']['causes']=causes
        out['counts']['answer_key']=None
        depth=100*mean(x['addressed'] for x in out['counts']['depth'])
        breadth=100*mean(x['addressed'] for x in out['counts']['breadth'])
        cause_share=100*mean(x['tested'] for x in causes) if causes else None
        out['count_percentages']={'depth_probes':depth,'breadth_probes':breadth,'candidate_causes':cause_share}
        depth_count=mean([depth,cause_share]) if cause_share is not None else depth
        out['indicators']={
            'Framing':component(judged(criteria,{'F'})),
            'Correctness':component(judged(criteria,{'Q'})),
            'Depth':component(judged(criteria,{'M'}),depth_count),
            'Breadth':component(judged(criteria,{'B'}),breadth),
            'Robustness':component(judged(criteria,{'R'}),run=robust,run_low=robust_low),
            'Rigor':component(judged(criteria,{'A','I'}))}
        partition=sum(out['indicators'][k]['judged']*w/100 for k,w in [('Framing',10),('Correctness',20),('Depth',20),('Breadth',15),('Robustness',15),('Rigor',20)])
    else:
        labels,oks,notes=PAPER[q][m]; ks=[c for c in criteria if c['id'].rsplit('-',1)[-1].startswith('K')]
        assert len(ks)==len(labels)==len(oks)==len(notes)
        out['counts']['findings']=[{'id':k['id'],'agent_verdict':label,'matches_reference':None,
                                    'evidence_ok':ok,'note':note,
                                    'sources':[attempt['attempt']+'/answer.md',
                                               *[attempt['attempt']+'/'+p for p in attempt['notebooks']]]}
                                   for k,label,ok,note in zip(ks,labels,oks,notes)]
        first=100*sum(c['weight']*min(c['level'],2)/2 for c in ks)/sum(c['weight'] for c in ks)
        second=100*sum(c['weight']*max(c['level']-2,0)/2 for c in ks)/sum(c['weight'] for c in ks)
        verdict=100*mean(x!='missing' for x in labels); support=100*mean(oks)
        out['count_percentages']={'findings_with_verdict':verdict,'evidence_ok':support,'matches_reference':None}
        out['indicators']={
            'Finding tests':component(first,verdict),
            'Right verdicts':component(second),
            'Method fidelity':component(judged(criteria,{'M'})),
            'Differences explained':component(judged(criteria,{'D'})),
            'Traceability':component(judged(criteria,{'R'}),support),
            'Robustness':component(run=robust,run_low=robust_low)}
        partition=sum(out['indicators'][k]['judged']*w/100 for k,w in [('Finding tests',35),('Right verdicts',35),('Method fidelity',10),('Differences explained',10),('Traceability',10)])
    assert abs(partition-out['original_criterion_total'])<1e-9, (q,m,partition)
    return out


def average(rows):
    keys=rows[0]['indicators'];out={}
    for key in keys:
        out[key]={}
        for part in ('judged','counted','run','run_lower','combined','combined_lower'):
            values=[r['indicators'][key][part] for r in rows]
            assert all(v is None for v in values) or all(v is not None for v in values)
            out[key][part]=mean(values) if values[0] is not None else None
    return out


def f(x):
    return '—' if x is None else f'{x:.2f}'


def cell(c):
    total=interval(c['combined_lower'],c['combined'])
    run=interval(c['run_lower'],c['run'])
    return f"{f(c['judged'])} / {f(c['counted'])} / {run} → **{total}**"


def interval(low,high):
    return f(high) if low is None or f(low)==f(high) else f(low)+'–'+f(high)


def main():
    src_score=SNAPSHOT/'scores.json';src_evidence=SNAPSHOT/'evidence.json'
    originals={str(p):sha(p) for p in (src_score,src_evidence)}
    scores=json.loads(src_score.read_text()); evidence=json.loads(src_evidence.read_text())
    audit=json.loads((HERE/'run-measures.json').read_text())
    runs={(a['query'],a['method']):a for a in audit['attempts']}
    rows=[per_attempt(q,m,evidence,scores['queries'][q]['methods'][m],runs[q,m])
          for q in sorted(scores['queries']) for m in METHODS]
    assert len(rows)==51
    results={'status':'provisional_aspect_trial_not_rejudged','generated_at_jst':datetime.now(timezone(timedelta(hours=9))).isoformat(),
             'sources':originals,'aspect_spec_sha256':sha(HERE.parents[2]/'evaluation/ASPECT_SCORES.md'),
             'aggregation':'equal task weight within task type; one pinned attempt per task/method',
             'missing_reference_counts':['answer_key.result','findings.matches_reference'],
             'attempts':rows,'summary':{}}
    lines=['# 2026-10-06 审阅批次：六指标只读试算','',
           '**不是重评，也不是正式基准成绩。** 原有51次尝试的0–4档位与主评分均原样保留。新增内容只有无需参考答案的计数与运行测量；没有改动服务器上的任何运行文件。',
           '', '采用本机 `benchmarking/evaluation/ASPECT_SCORES.md` v1.0。开放题13题×3方法=39次；论文验证4题×3方法=12次。按题等权，不按执行数、命题数或耗时加权。',
           '', '单元格：**判分 J / 计数 C / 运行 X → 混合指标**，全部为0–100。没有的部分显示 —。缺失参考的正确性计数不猜填，权重归还J。存在J和C（或J和X）时为0.75J+0.25C（或X）；只有J时等于J；仅运行的论文稳健性是交付与重复失败分的平均。区间来自无法确认错误末行的相邻失败对，不是统计置信区间。', '']
    names={'Framing':'问题拆解','Correctness':'正确性','Depth':'深度','Breadth':'广度','Robustness':'稳健性','Rigor':'严谨性',
           'Finding tests':'命题检验','Right verdicts':'判定正确','Method fidelity':'方法忠实','Differences explained':'差异归因','Traceability':'可追溯'}
    for typ,title in [('open_problem','开放题'),('paper_reproduction','论文验证题')]:
        subset=[r for r in rows if r['type']==typ]; assert len(subset)==(39 if typ=='open_problem' else 12)
        avg={m:average([r for r in subset if r['method']==m]) for m in METHODS}
        results['summary'][typ]=avg
        lines += [f'## {title}', '', '题目：'+', '.join(sorted({r['query'] for r in subset})), '',
                  '| 指标 | OceanX | Claude | Finch |','|---|---|---|---|']
        for k in avg['OceanX']:
            lines.append('| '+names[k]+' | '+' | '.join(cell(avg[m][k]) for m in METHODS)+' |')
        lines += ['', '计数和运行细项（先逐题求比例，再对题目平均）：','',
                  '| 细项 | OceanX | Claude | Finch |','|---|---|---|---|']
        ck=['depth_probes','candidate_causes','breadth_probes'] if typ=='open_problem' else ['findings_with_verdict','evidence_ok']
        cn={'depth_probes':'深度探针覆盖 %','candidate_causes':'已测试候选原因 %（仅分歧题）','breadth_probes':'广度探针覆盖 %',
            'findings_with_verdict':'有判定的命题 %','evidence_ok':'有可追溯执行支持的命题 %'}
        for key in ck:
            lines.append('| '+cn[key]+' | '+' | '.join(f(mean(r['count_percentages'][key] for r in subset if r['method']==m and r['count_percentages'][key] is not None)) for m in METHODS)+' |')
        lines.append('| 交付 %（completed 且 answer.md 非空） | '+' | '.join(f(mean(r['delivery'] for r in subset if r['method']==m)) for m in METHODS)+' |')
        lines.append('| 重复失败分 | '+' | '.join(interval(mean(r['repeated_failure']['score_lower'] for r in subset if r['method']==m),mean(r['repeated_failure']['score'] for r in subset if r['method']==m)) for m in METHODS)+' |')
        lines += ['', '未计入指标的成本：','', '| 方法 | 原主评分均值 | 逐项评分加权均值 | 总耗时 h | 每题均值 min | token 合计 M¹ | 模型调用¹ | 执行数 | 重复对：已确认 / 可能额外 |',
                  '|---|---:|---:|---:|---:|---:|---:|---:|---|']
        for m in METHODS:
            rs=[r for r in subset if r['method']==m]; tokens=[r['original_recorded_tokens'] for r in rs]; calls=[r['original_recorded_model_calls'] for r in rs]
            lines.append('| '+m+' | '+f(mean(r['original_primary_score'] for r in rs))+' | '+f(mean(r['original_criterion_total'] for r in rs))+' | '+f(sum(r['elapsed_seconds'] for r in rs)/3600)+' | '+f(mean(r['elapsed_seconds'] for r in rs)/60)+' | '+(f(sum(tokens)/1e6) if all(x is not None for x in tokens) else '不可全量确定')+' | '+(str(sum(calls)) if all(x is not None for x in calls) else '不可全量确定')+' | '+str(sum(r['repeated_failure']['executions'] for r in rs))+' | '+str(sum(r['repeated_failure']['repeated_failures'] for r in rs))+' / '+str(sum(r['repeated_failure']['ambiguous_pairs'] for r in rs))+' |')
        lines.append('')
    lines += ['## 本次试算暴露的限制','',
        '1. **沿用原判分的边界。** Claude Q15的原主评分为0（needs_interaction），原审阅同时保留了52.5分的产物逐项档位。本试算按要求直接使用这些逐项档位，不把主评分改成52.5，也不把档位清零。OceanX Q27、Finch Q08/Q20/Q23沿用原审阅的全零档位，即使部分执行产物仍可用于覆盖计数。以后正式评分对失败尝试的处理不能通过本次试算偷偷改变。',
        '2. **无需参考答案不等于完全客观。** 探针/候选原因是否被处理和命题证据是否可追溯仍需要人工对保存产物作存在性判断。`results.json`保留逐项布尔值、开放题证据位置与摘录、论文题来源文件与说明，以及排除理由；只记录做没做，不重新评价诊断是否算对。列出的复合测试须完成所要求的联系，单独提及其中一个变量不算完整处理。答案键正确性与判定吻合参考均为null。',
        '3. **交付只是协议交付，不是科研交付。** 按既定定义，Finch Q09/Q15/Q24/Q27的非空阻塞/计划报告，以及Claude Q25的预处理结束文字也算交付。它们没有因此被提高原科学评分。形式交付率会高估有用交付，需要Owner在冻结指标前看到这一点。',
        '4. **Finch按一次整本执行计一个execution。** `code_runs.jsonl`的running和终态共享execution_id，只计终态一次；同一replay里多个单元报错也只计一次失败。使用该执行最后一个错误的末行（剥去ANSI显示码、折叠空白），和前一次执行比较；成功会断开失败链。不把仅同为NameError当成同一个错误，也不把正常list_workdir、非法bash调用或编辑次数计成代码执行。',
        '5. **旧错误重放仍被算入既定指标。** 没有把Finch旧单元错误剔除；例如Q08持续重放旧NameError。多工具编辑的一轮只保存最后一次replay的完整观察，前一次的末行可能无法还原；对这些相邻失败对给上下界。`persistent_error_cell_pairs`是额外诊断，不能当作主动重试次数。',
        '6. **执行分母不可直接横比。** OceanX包括沙箱shell/持久kernel，Claude是Bash等命令工具的返回（含被工具阻止的命令；按error标记），Finch是全notebook重跑。大量成功的检查命令可稀释OceanX/Claude的重复失败比例；Finch旧错误可在多个编辑中反复进入分子。',
        '7. **零次执行按文档得0，不是100。** 无代码的Finch阻塞尝试因此重复失败分为0；这同时反映没有做分析和没有重复失败，两者不能只从这一分数区分。原审阅仍保留最低方法档位，没有在本次重评为全零。',
        '8. **新混合值不是新的rubric总分。** 判分部分的100点分配已验证还原原逐项加权分；加入计数和运行后的六轴不能再加成新的科学总分。“判定正确”的J只是旧K档位的高半段，不是本次独立核准了判定正确。',
        '', '¹ 成本表沿用10月6日审阅记录中的已校核token/调用汇总，不改变`result.json`：OceanX来自per-call ledger补充；Finch来自result.external_usage；Claude来自result的整调用/缓存token口径，调用数不可全量确定。OceanX在result内的coordinator_usage/expert_usage token总数仍为0，不能把该0当成真实成本。缓存input包括在总input中，只加一次；各方法自报口径/失败用量缺失限制仍在。',
        '', '## 对待定设置的建议（未冻结文档）','',
        '- 当前0.75J+0.25C的覆盖混合值可以作描述性试算，但覆盖数不是证据正确性，不能替代原rubric。两项参考计数缺失，本次不能验证最终三部分混合的效果。',
        '- 重复失败保留为诊断表更稳妥；这批数据不足以支持把它当作跨方法同尺度的稳健性评分。若Owner仍保留，应连同执行分母、重放原因和缺失末行范围公布，不能只画一个分数。',
        '- 本次只产出试算，没有修改`ASPECT_SCORES.md`的混合比例或冻结状态。',
        '', '## 逐题计数及运行审计','',
        '| 题 | 方法 | 原主分 | 深度探针 | 候选原因 | 广度探针 | 有判定命题 | evidence_ok | 交付 | 执行/失败 | 重复对已知/额外可能 |',
        '|---|---|---:|---|---|---|---|---|---:|---|---|']
    for r in rows:
        c=r['counts'];d=c.get('depth');b=c.get('breadth');ca=c.get('causes');ks=c.get('findings')
        frac=lambda xs,key: str(sum(x[key] for x in xs))+'/'+str(len(xs)) if xs else '—'
        st=r['repeated_failure']
        lines.append('| '+r['query']+' | '+r['method']+' | '+f(r['original_primary_score'])+' | '+frac(d,'addressed')+' | '+frac(ca,'tested')+' | '+frac(b,'addressed')+' | '+(str(sum(x['agent_verdict']!='missing' for x in ks))+'/'+str(len(ks)) if ks else '—')+' | '+frac(ks,'evidence_ok')+' | '+f(r['delivery'])+' | '+str(st['executions'])+'/'+str(st['failures'])+' | '+str(st['repeated_failures'])+'/'+str(st['ambiguous_pairs'])+' |')
    lines += ['', '逐个判分、计数摘录、运行路径及重复错误对在 [results.json](results.json) 和 [run-measures.json](run-measures.json)。本次只写本机此独立试算目录；原中英文审阅HTML、运行目录、评分文档、源码及数据库均未改动。', '']
    (HERE/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    (HERE/'summary.md').write_text('\n'.join(lines))
    assert all(sha(Path(p))==h for p,h in originals.items())
    print('Verified 51 reused criterion records; 39 open / 12 paper; original score and evidence hashes unchanged.')
    for typ,ss in results['summary'].items():
        print(typ)
        for axis in ss['OceanX']:
            print(axis,[(m,round(ss[m][axis]['combined_lower'],2),round(ss[m][axis]['combined'],2)) for m in METHODS])


if __name__=='__main__':
    main()

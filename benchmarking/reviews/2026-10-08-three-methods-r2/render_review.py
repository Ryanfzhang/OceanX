"""Refresh the historical bilingual renderer without changing the old report.

Large read-only evidence snapshots stay outside the repository. Only the HTML,
small audit/score metadata and new figures belong to this report package.
"""
import hashlib
import json
import struct
from pathlib import Path

OUT = Path(__file__).resolve().parent
BASE = Path('/Users/ryanzhang/.codex/visualizations/2026/08/22/01a02889-8101-7d21-9d67-f7b62e1a6809')
WORK = BASE / 'benchmark-review-20261008-r2'
OLD = BASE / 'benchmark-review'
PREVIOUS = OUT.parent / '2026-10-08-three-methods'


def main():
    # Reserve image geometry before lazy loading so query-anchor jumps stay stable.
    manifest = json.loads((OUT / 'figure-manifest.json').read_text())
    for item in manifest:
        with (OUT / item['target']).open('rb') as figure:
            header = figure.read(24)
        assert header[:8] == b'\x89PNG\r\n\x1a\n', item['target']
        item['width'], item['height'] = struct.unpack('>II', header[16:24])
    (OUT / 'figure-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    source = (OLD / 'build_report.py').read_text()

    def change(before, after):
        nonlocal source
        assert source.count(before) == 1, (before[:100], source.count(before))
        source = source.replace(before, after)

    change('ROOT = Path(__file__).parent', 'ROOT = Path(' + repr(str(WORK)) + ')\nOUT = Path(' + repr(str(OUT)) + ')')
    change("MANIFEST = json.loads((ROOT/'figure-manifest.json').read_text())",
           "MANIFEST = json.loads((OUT/'figure-manifest.json').read_text())\n"
           "SELECTION = json.loads((OUT/'selection.json').read_text())\n"
           "PRIOR_SCORES = json.loads((Path(" + repr(str(PREVIOUS)) + ")/'scores.json').read_text())\n"
           "CHANGED = {(c['query'],c['method']) for c in SELECTION['changes']}")
    change("if q=='Q25' and m=='OceanX':", "if q=='Q25' and m=='OceanX' and name.startswith('fig-b111'):")
    change("The final answer withdraws some interannual/control panels. This original figure is not automatically valid evidence.",
           "The report corrects an earlier depth-axis error in this B1.11 analysis. Interpret these saved panels only against the corrected numeric report, not as independently validated evidence.")
    change('最终答案撤回部分年际/控制面板；这张原图并不自动构成有效证据。',
           'B1.11报告修正了先前深度轴错误；这些保存面板应结合修正数值报告阅读，不是独立验证的证据。')
    change("    elif q=='Q07' and m=='OceanX' and 'mld' in name:",
           "    elif q=='Q27' and m=='OceanX' and name=='mhw-intensity-trend-conventions.png':\n"
           "        warning=tr('The Expert explicitly declares panel (c) invalid; use the corrected numeric tables.', 'Expert明确声明(c)面板无效；请使用修正数值表。',lang)\n"
           "    elif q=='Q08' and m=='Finch' and name=='fig_geo_speed.png':\n"
           "        warning=tr('Saved from cell 17 before the spacing-unit correction; this map retains erroneous speeds and was not redrawn.', '单元17保存于间距单位修正之前；此图仍含错误速度，没有重画。',lang)\n"
           "    elif q=='Q20' and m=='Finch' and name=='fig5_monthly_maps.png':\n"
           "        warning=tr('Vorticity contours use a per-degree derivative divided by grid-cell spacing, inflating magnitude by approximately 12×.', '涡度等值线把每度导数除以网格间距，量级约放大12倍。',lang)\n"
           "    elif q=='Q20' and m=='Finch' and name=='fig6_anomaly_hovmoller.png':\n"
           "        warning=tr('The calendar composite after subtracting that same calendar climatology is near zero by construction, not a test of absent propagation.', '减去同一日历气候态后再做日历合成，按构造接近零，不能用于检验是否存在传播。',lang)\n"
           "    elif q=='Q24' and m=='Finch':\n"
           "        warning=tr('Area/volume diagnostics omit longitude spacing and are inflated approximately 12×; standing footprint ratios do not measure export flux. Saved figures are shown unchanged.', '面积/体积诊断漏乘经度间距，约放大12倍；现存覆盖比例不是输出通量。保存图原样展示。',lang)\n"
           "    elif q=='Q25' and m=='Claude':\n"
           "        warning=tr('Hot-area and LC/large-eddy shares use different structure masks; the reported variance shares omit covariance and are not total-variance attribution.', '高热区域与LC/大涡占比使用不同结构掩码；所报方差占比遗漏协方差，不是总方差归因。',lang)\n"
           "    elif q=='Q27' and m=='Finch':\n"
           "        warning=tr('Raw and detrended daily SD coincide by construction after subtracting one constant per year; this panel is not independent evidence of stationary variability. Detector uses truncated JJAS calendar windows.', '每年减一个常数后原始与去趋势逐日SD按构造相同，该面板不是变率稳定的独立证据；检测窗口使用截断JJAS日历。',lang)\n"
           "    elif q=='Q07' and m=='OceanX' and 'mld' in name:")
    change('<img loading="lazy" src="{esc(img["target"])}"',
           '<img loading="lazy" width="{img["width"]}" height="{img["height"]}" src="{esc(img["target"])}"')
    change("    if r['disposition']=='incomplete':\n        out.append(f'<p class=\"notice\">",
           "    out.append('<p class=\"meta\">'+tr('New attempt reviewed in this update.' if (q,m) in CHANGED else 'Unchanged attempt; previous October 8 assessment retained.', '本次更新审阅的新尝试。' if (q,m) in CHANGED else '尝试未变；保留前一份10月8日评分。',lang)+'</p>')\n"
           "    if r['disposition']=='incomplete':\n        out.append(f'<p class=\"notice\">")
    change('/ 17 queries / 51 attempts', '/ 17 queries / 51 selected attempts / 5 updates')
    change('One attempt per method and query; no frozen numerical oracle and no independent re-execution.',
           'Latest available terminal attempt per method and query; 5 new assessments and 46 retained assessments. No frozen numerical oracle and no independent re-execution.')
    change('每方法每题一次运行；没有冻结数值参考，也没有独立重算。',
           '每方法每题选择最新可用终态尝试；更新5份、保留46份评分。没有冻结数值参考，也没有独立重算。')
    change("'<nav aria-label=\"Queries\"><a href=\"#protocol\">'", "'<nav aria-label=\"Queries\"><a href=\"#updates\">'+tr('Updates','本次更新',lang)+'</a><a href=\"#protocol\">'")
    change('Terminal failed/timed-out runs and empty scientific deliveries receive zero outcome score. Claude Q15 needs_interaction receives outcome zero, but its substantial artifacts have a separate 52.5 quality reading.',
           'For longitudinal comparability this refresh preserves the October 6 provisional scoring convention; it is not a fresh application of the newer formal partial-credit contract. All five replacements now have completed answers and executed notebooks and are graded on scientific evidence. Previously empty deliveries are superseded, not retained as current failures.')
    change('终态失败/超时及科学交付为空，结果分计0。Claude Q15为needs_interaction，结果分0，但实质产物另给52.5质量读数。',
           '为便于历史对照，本次沿用10月6日暂定评分口径，非重新套用新版正式部分产物给分规则。五份替换现均有完整答案与执行notebook，按科学证据评分；旧空交付已被替代，不保留为当前失败。')
    change('Claude Q15’s artifact-only 52.5 is listed separately, not included in that conditional set.',
           'This table includes only the selected latest attempts: superseded failed/interaction attempts and their elapsed costs are not added to these means or time totals; see the attempt inventory for history.')
    change('Claude Q15仅产物52.5单列，不计入这个条件集合。',
           '此表仅包括选定最新尝试；被替代的失败/交互尝试及耗时不加入均值或总时间，历史见尝试清单。')
    change('and two deliveries are incomplete.', 'and all 17 selected deliveries now contain executed analysis; proxy-based forcing claims and Q25 variance attribution remain problematic.')
    change('且两次交付不完整。', '且17份选定交付现均含执行分析；代理强迫声明与Q25方差归因仍有问题。')
    change('but seven of these attempts fail or lack executed scientific evidence;',
           'all 17 selected deliveries now contain executed scientific work, including four formerly empty reruns;')
    change('但本批七次尝试失败或缺执行科学证据，',
           '17份选定交付现均有执行科学工作，包括四份此前空交付的重跑，')
    change('that raises an integration/execution concern before any broad claim about Finch’s science quality.',
           'the previous empty-delivery problem is resolved in this selected set, but numerical, event-identity and causal-proxy defects still limit scientific quality.')
    change('应先重视接入/执行问题，再讨论其普遍科研能力。',
           '选定集合中的旧空交付问题已解决，但数值、事件身份与因果代理缺陷仍限制科学质量。')
    change('All 17 cases are reviewed, including failed and non-delivering attempts. The bar chart uses the same primary scores as the table.',
           'All 17 queries and 51 selected executed deliveries are reviewed. The bar chart uses the same primary scores as the table; superseded empty attempts are not plotted.')
    change('17道题均已审阅，包括失败和未交付尝试。柱状图与表格使用相同主分数。',
           '17道题、51份选定执行交付均已审阅。柱状图与表格使用相同主分数，被替代的空尝试不再绘入。')
    change('Short failed/unexecuted Finch runs are not speed wins.',
           'All currently selected deliveries are executed; earlier short failed/unexecuted runs are excluded and are not speed wins.')
    change('Finch较短的失败/未执行运行不是速度优势。',
           '当前选定交付均已执行；旧较短失败/未执行尝试已排除，不是速度优势。')
    change('Report package: review-en.html; review-zh.html; assets/',
           'Report package: review-en.html; review-zh.html; scores.json; selection.json; audit.json; figure-manifest.json; assets/\\nShared unchanged figures: ../2026-10-06-three-methods/assets/ and ../2026-10-08-three-methods/assets/')
    change('Only the two new HTML reports and copied output images are published.',
           'The refreshed HTML, small audit metadata and 26 new output images are published. The 471 reused figures reference the intact neighboring October 6 and earlier October 8 report directories; keep all three directories together.')
    change('只发布两份新的HTML与复制的输出图，',
           '发布更新HTML、小型审计元信息及26张新输出图。471张复用图引用相邻且完整的10月6日及前一份10月8日报告目录，三个目录须放在一起；')
    change("    for q,c in DATA.items():\n        out.append(f'<section class=\"query\"",
           "    out.append(update_html(lang))\n    for q,c in DATA.items():\n        out.append(f'<section class=\"query\"")

    update_source = '''
def update_html(lang):
    out=['<section class="panel" id="updates"><h2>'+tr('October 8 second refresh — five reruns','10月8日第二次更新 — 五份重跑',lang)+'</h2>']
    out.append('<div class="notice"><p>'+tr('Claude Q25 and Finch Q09/Q15/Q24/Q27 now have completed answers and executed notebooks. These are five replacement attempts, not a new matched three-method trial. Selection uses the newest available terminal attempt, never the highest score. The other 46 assessments and both historical reports remain unchanged.', 'Claude Q25与Finch Q09/Q15/Q24/Q27现均有完整答案及执行notebook。这是五份替换尝试，不是新的匹配三方法试验；按最新可用终态尝试选择，不按最高分选择。其他46份评分及两份历史报告不变。',lang)+'</p></div>')
    out.append('<p class="meta">'+tr('Read-only evidence snapshot collected on October 8, 2026; report timestamps use JST. Runtime “completed” is not scientific validation.', '2026年10月8日只读收集证据；报告时间统一JST。“completed”运行状态不是科学验证。',lang)+'</p>')
    out.append('<p><a href="../2026-10-08-three-methods/review-'+lang+'.html">'+tr('Previous October 8 report','前一份10月8日报告',lang)+'</a> · <a href="selection.json">'+tr('Attempt selection and answer hashes','尝试选择及答案哈希',lang)+'</a> · <a href="scores.json">'+tr('Score audit data','评分审计数据',lang)+'</a></p>')
    out.append('<div class="table-wrap"><table><thead><tr><th>Query</th><th>'+tr('Method','方法',lang)+'</th><th>'+tr('Old → new score','旧→新分数',lang)+'</th><th>'+tr('Old → new state','旧→新状态',lang)+'</th><th>'+tr('New attempt minutes','新尝试分钟',lang)+'</th></tr></thead><tbody>')
    for c in SELECTION['changes']:
        q,m=c['query'],c['method']; old=PRIOR_SCORES['queries'][q]['methods'][m]; new=DATA[q]['methods'][m]
        out.append('<tr><td><a href="#'+q+'">'+label(q)+'</a></td><td>'+m+'</td><td class="num">'+fmt(old['score'])+' → '+fmt(new['score'])+'</td><td>'+esc(c['old_status'])+' → '+esc(c['new_status'])+'</td><td class="num">'+f"{new['elapsed_seconds']/60:.1f}"+'</td></tr>')
    out.append('</tbody></table></div><p class="meta">'+tr('Higher scores primarily reflect replacement of empty deliveries by executed analyses, not a measured causal effect of code changes. Finch Q24 still has an approximately 12× area/volume error; Claude Q25 variance shares omit covariance. Figures remain unedited and carry warnings. OceanX has no replacements in this refresh.', '分数上涨主要反映空交付被执行分析替代，不是代码变化的因果效果测量。Finch Q24仍有约12倍面积/体积错误，Claude Q25方差占比遗漏协方差；图原样保留并加提醒。本次OceanX无替换结果。',lang)+'</p></section>')
    return ''.join(out)

'''
    change('def make_report(lang):', update_source + '\ndef make_report(lang):')
    head, tail = source.split("scores={'status':", 1)
    tail = "scores={'status':" + tail
    tail = tail.replace("(ROOT/'scores.json')", "(OUT/'scores.json')")
    tail = tail.replace("(ROOT/f'review-{lang}.html')", "(OUT/f'review-{lang}.html')")
    tail = tail.replace("(ROOT/f).read_bytes()", "(OUT/f).read_bytes()")
    tail = tail.replace("(ROOT/'audit.json')", "(OUT/'audit.json')")
    source = head + tail
    namespace = {'__file__': str(OUT / 'render_review.py'), '__name__': '__main__'}
    exec(compile(source, str(OUT / 'render_review.py'), 'exec'), namespace)
    data = namespace['DATA']
    old = namespace['PRIOR_SCORES']
    changed = namespace['CHANGED']
    for q, case in data.items():
        for method, record in case['methods'].items():
            if (q, method) not in changed:
                before = old['queries'][q]['methods'][method]
                assert record['score'] == before['score'], (q, method)
                assert record['levels'] == before['levels'], (q, method)
                assert record['reasons'] == before['reasons'], (q, method)
                assert record['answer_sha256'] == before['answer_sha256'], (q, method)
    scores = json.loads((OUT / 'scores.json').read_text())
    scores['refresh'] = {'replacements': namespace['SELECTION']['changes'],
                         'unchanged_assessments': 46,
                         'selection_rule': 'latest available terminal attempt; never best score',
                         'historical_report': '../2026-10-08-three-methods'}
    (OUT / 'scores.json').write_text(json.dumps(scores, ensure_ascii=False, indent=2) + '\n')
    audit = json.loads((OUT / 'audit.json').read_text())
    audit['score_sha256'] = hashlib.sha256((OUT / 'scores.json').read_bytes()).hexdigest()
    audit['unchanged_assessments_verified'] = 46
    audit['new_assessments'] = 5
    audit['reused_figures'] = 471
    audit['new_figures'] = 26
    (OUT / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    print('Verified: 46 unchanged scores, levels, reasons and answer hashes; 5 new assessments.')


if __name__ == '__main__':
    main()

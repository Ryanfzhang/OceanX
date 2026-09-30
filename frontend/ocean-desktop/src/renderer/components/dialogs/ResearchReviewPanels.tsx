import {useCallback, useEffect, useState} from 'react';

import {useUiLanguage} from '../../i18n.js';
import {NODE_LABELS, parseLabelCandidates, parsePolicyOverview, type LabelCandidate, type NodeLabel, type PolicyOverview} from '../../research-review.js';
import type {EventPayload} from '../../types.js';
import type {LessonRequest} from './ResearchLessonsDialog.js';

function useReview(request: LessonRequest, taskId: string | null) {
  const [labels, setLabels] = useState<LabelCandidate[]>([]);
  const [policies, setPolicies] = useState<PolicyOverview | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const send = useCallback((type: string, payload: EventPayload) => {
    setBusy(true); setNotice(null);
    request(type, payload, (result) => {
      setLabels(parseLabelCandidates(result));
      setPolicies(parsePolicyOverview(result));
      setBusy(false);
    }, (message) => {setNotice(message); setBusy(false);});
  }, [request]);
  useEffect(() => {send('research.review.get', taskId ? {task_id: taskId} : {});}, [send, taskId]);
  return {labels, policies, busy, notice, send};
}

export function BranchLabelPanel({request, taskId}: {request: LessonRequest; taskId: string | null}): React.JSX.Element {
  const {text} = useUiLanguage();
  const {labels, busy, notice, send} = useReview(request, taskId);
  const names: Record<NodeLabel, string> = {
    'decision-changing': text('Changed the conclusion', '改变了结论'),
    'informative-but-not-decisive': text('Informative', '有信息量'),
    'misleading-or-wasteful': text('Wasteful', '浪费'),
  };
  if (!taskId) return <p className="lessons-empty">{text('Open a finished research task to review its branches.', '请打开一个已完成的研究任务来审核其分支。')}</p>;
  return <section aria-label={text('Branch labels', '分支标注')}>
    <p className="lessons-intro">{text('Only a few branches need your view: top-level branches, branches the answer cites, and cases where the automatic and model labels disagree. Everything else is labelled automatically.', '只需审核少数分支：顶层分支、答案引用的分支，以及自动标注与模型判断不一致的分支。其余分支自动标注。')}</p>
    {notice ? <p className="lessons-notice" role="status">{notice}</p> : null}
    {labels.length ? <ul className="lesson-active-list">{labels.map((item) => <li key={item.node_id} className="lesson-active branch-label">
      <div><strong>{item.node_id}</strong> {item.question}<br /><small>{item.status}{item.suggested ? ` · ${text('suggested', '建议')}: ${names[item.suggested]} (${item.suggested_source})` : ''}</small>{item.result ? <p className="lesson-rationale">{item.result}</p> : null}</div>
      <div className="branch-label-actions">{NODE_LABELS.map((value) => <button key={value} disabled={busy} className={item.human === value ? 'primary' : ''} aria-pressed={item.human === value} onClick={() => send('research.labels.set', {task_id: taskId, node_id: item.node_id, label: value})}>{names[value]}</button>)}</div>
    </li>)}</ul> : <p className="lessons-empty">{busy ? '' : text('Nothing to review for this task yet.', '该任务暂无需要审核的分支。')}</p>}
  </section>;
}

export function PolicyPanel({request, taskId}: {request: LessonRequest; taskId: string | null}): React.JSX.Element {
  const {text} = useUiLanguage();
  const {policies, busy, notice, send} = useReview(request, taskId);
  return <section aria-label={text('Research policies', '研究策略')}>
    <p className="lessons-intro">{text('A policy is an experiment arm for how OceanX explores the research tree. The choice applies to new tasks in this project; paired runs decide whether one is better.', '策略是 OceanX 探索研究树方式的实验组。所选策略用于本项目的新任务；由成对运行判断哪个更好。')}</p>
    {notice ? <p className="lessons-notice" role="status">{notice}</p> : null}
    {policies ? <ul className="lesson-active-list">{policies.available.map((option) => <li key={option.name} className="lesson-active">
      <div><strong>{option.name}</strong><br /><small>{option.description}</small></div>
      {policies.active === option.name ? <span className="lesson-kind">{text('Active', '使用中')}</span> : <button disabled={busy} onClick={() => send('research.policies.activate', {name: option.name})}>{text('Use', '使用')}</button>}
    </li>)}</ul> : null}
  </section>;
}

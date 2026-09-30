import {useCallback, useEffect, useState} from 'react';
import {Archive, BookOpenCheck, Check, LoaderCircle, RefreshCw, Sparkles, X} from 'lucide-react';

import {useUiLanguage} from '../../i18n.js';
import {approvalProblem, decisionPayload, parseLessonOverview, wordCount, type ActiveLesson, type EvidenceTask, type LessonOverview, type LessonProposal} from '../../lesson-review.js';
import type {EventPayload} from '../../types.js';
import {ModalDialog} from './ModalDialog.js';
import {BranchLabelPanel, PolicyPanel} from './ResearchReviewPanels.js';

export type LessonRequest = (
  type: string,
  payload: EventPayload,
  onResult: (result: EventPayload) => void,
  onError: (message: string) => void,
) => void;

function EvidenceList({tasks, label}: {tasks: EvidenceTask[]; label: string}): React.JSX.Element | null {
  if (!tasks.length) return null;
  return <details className="lesson-evidence"><summary>{label} ({tasks.length})</summary><ul>{tasks.map((task) => <li key={task.task_key}><code>{task.task_key.slice(0, 8)}</code> {task.question || '—'}</li>)}</ul></details>;
}

function ProposalCard({proposal, overview, busy, onDecide}: {
  proposal: LessonProposal;
  overview: LessonOverview;
  busy: boolean;
  onDecide: (proposal: LessonProposal, decision: 'approve' | 'reject', draft: {text: string; appliesWhen: string}, reason: string) => void;
}): React.JSX.Element {
  const {text} = useUiLanguage();
  const [draft, setDraft] = useState({text: proposal.text, appliesWhen: proposal.applies_when});
  const [reason, setReason] = useState('');
  const problem = approvalProblem(draft, proposal, overview);
  const problemText: Record<string, string> = {
    'empty-text': text('Lesson text is empty.', '经验内容为空。'),
    'text-too-long': text(`Keep the lesson within ${overview.limits.max_words} words.`, `经验内容不超过 ${overview.limits.max_words} 个词。`),
    'empty-condition': text('Say when the lesson applies.', '请说明适用条件。'),
    'condition-too-long': text(`Keep the condition within ${overview.limits.max_condition_words} words.`, `适用条件不超过 ${overview.limits.max_condition_words} 个词。`),
    'role-full': text('This role already has the maximum number of lessons; retire one first.', '该角色的经验已达上限，请先停用一条。'),
  };
  const retire = proposal.kind === 'retire';
  return <article className="lesson-card" aria-label={text('Lesson proposal', '经验提议')}>
    <header>
      <span className={`lesson-role lesson-role-${proposal.role}`}>{proposal.role === 'coordinator' ? text('Guidance lesson · Coordinator', '指导经验 · 协调者') : text('Method lesson · Experts', '方法经验 · 专家')}</span>
      {retire ? <span className="lesson-kind">{text(`Retire ${proposal.lesson_id ?? ''}`, `停用 ${proposal.lesson_id ?? ''}`)}</span> : <span className="lesson-kind">{text('New lesson', '新经验')}</span>}
    </header>
    {retire ? <p className="lesson-text">{proposal.text}<br /><small>{text('Applies when', '适用条件')}: {proposal.applies_when}</small></p> : <>
      <label className="lesson-field">{text('Lesson', '经验')} <small>{wordCount(draft.text)}/{overview.limits.max_words}</small>
        <textarea rows={2} value={draft.text} disabled={busy} onChange={(event) => setDraft((current) => ({...current, text: event.target.value}))} />
      </label>
      <label className="lesson-field">{text('Applies when', '适用条件')} <small>{wordCount(draft.appliesWhen)}/{overview.limits.max_condition_words}</small>
        <input value={draft.appliesWhen} disabled={busy} onChange={(event) => setDraft((current) => ({...current, appliesWhen: event.target.value}))} />
      </label>
    </>}
    {proposal.rationale ? <p className="lesson-rationale">{text('Why proposed', '提议理由')}: {proposal.rationale}</p> : null}
    <EvidenceList tasks={proposal.evidence_tasks.supporting} label={text('Supporting tasks', '支持的任务')} />
    <EvidenceList tasks={proposal.evidence_tasks.counter} label={text('Counterexamples', '反例')} />
    <label className="lesson-field">{text('Note (optional)', '备注（可选）')}<input value={reason} disabled={busy} onChange={(event) => setReason(event.target.value)} /></label>
    {problem ? <p className="lesson-problem" role="status">{problemText[problem]}</p> : null}
    <footer>
      <button disabled={busy} onClick={() => onDecide(proposal, 'reject', draft, reason)}><X size={14} />{text('Reject', '拒绝')}</button>
      <button className="primary" disabled={busy || Boolean(problem)} onClick={() => onDecide(proposal, 'approve', draft, reason)}><Check size={14} />{retire ? text('Approve retirement', '同意停用') : text('Approve', '批准')}</button>
    </footer>
  </article>;
}

function ActiveLessonRow({lesson, busy, onRetire}: {lesson: ActiveLesson; busy: boolean; onRetire: (lesson: ActiveLesson, reason: string) => void}): React.JSX.Element {
  const {text} = useUiLanguage();
  const [retiring, setRetiring] = useState(false);
  const [reason, setReason] = useState('');
  return <li className="lesson-active">
    <div><strong>{lesson.id}</strong> {lesson.text}<br /><small>{text('Applies when', '适用条件')}: {lesson.applies_when} · {text(`${lesson.evidence_tasks.supporting.length} supporting / ${lesson.evidence_tasks.counter.length} counter`, `${lesson.evidence_tasks.supporting.length} 个支持 / ${lesson.evidence_tasks.counter.length} 个反例`)}{lesson.edited ? text(' · edited by reviewer', ' · 审核者修改过') : ''}</small></div>
    {retiring ? <div className="lesson-retire"><input autoFocus placeholder={text('Reason for retiring', '停用理由')} value={reason} onChange={(event) => setReason(event.target.value)} /><button disabled={busy || !reason.trim()} onClick={() => onRetire(lesson, reason)}>{text('Retire', '停用')}</button><button onClick={() => setRetiring(false)}>{text('Cancel', '取消')}</button></div>
      : <button disabled={busy} title={text('Retire lesson', '停用经验')} onClick={() => setRetiring(true)}><Archive size={14} /></button>}
  </li>;
}

export function ResearchLessonsDialog({open, onClose, request, onPendingCount, taskId = null}: {
  open: boolean;
  onClose: () => void;
  request: LessonRequest;
  onPendingCount?: (count: number) => void;
  taskId?: string | null;
}): React.JSX.Element | null {
  const {text} = useUiLanguage();
  const [tab, setTab] = useState<'lessons' | 'labels' | 'policies'>('lessons');
  const [overview, setOverview] = useState<LessonOverview | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const apply = useCallback((result: EventPayload) => {
    const next = parseLessonOverview(result);
    if (next) {setOverview(next); onPendingCount?.(next.pending.length);}
    setBusy(false);
  }, [onPendingCount]);
  const fail = useCallback((message: string) => {setNotice(message); setBusy(false);}, []);
  const send = useCallback((type: string, payload: EventPayload, after?: (result: EventPayload) => void) => {
    setBusy(true); setNotice(null);
    request(type, payload, (result) => {apply(result); after?.(result);}, fail);
  }, [apply, fail, request]);

  useEffect(() => {if (open) send('research.lessons.list', {});}, [open, send]);
  if (!open) return null;

  const consolidate = (propose: boolean) => send('research.lessons.consolidate', {propose}, (result) => {
    const mining = result.mining as Record<string, unknown> | undefined;
    const cleanup = result.consolidation as Record<string, unknown> | undefined;
    const parts = [];
    if (cleanup) parts.push(text(`Digested ${String(cleanup.digested ?? 0)}, archived ${String(cleanup.archived ?? 0)} task records.`, `已摘要 ${String(cleanup.digested ?? 0)} 个、归档 ${String(cleanup.archived ?? 0)} 个任务记录。`));
    if (mining) parts.push(text(`${String(mining.created ?? 0)} new proposals; ${Array.isArray(mining.rejected) ? mining.rejected.length : 0} rejected by the limits.`, `新增 ${String(mining.created ?? 0)} 条提议；${Array.isArray(mining.rejected) ? mining.rejected.length : 0} 条因不符合限制被丢弃。`));
    setNotice(parts.join(' ') || null);
  });

  const roles = [
    {key: 'coordinator', title: text('Guidance lessons (Coordinator)', '指导经验（协调者）')},
    {key: 'expert', title: text('Method lessons (Experts)', '方法经验（专家）')},
  ] as const;

  const tabs = [
    {key: 'lessons', label: text('Lessons', '经验')},
    {key: 'labels', label: text('Branch labels', '分支标注')},
    {key: 'policies', label: text('Policies', '策略')},
  ] as const;
  return <ModalDialog ariaLabel={text('Research review', '研究审核')} className="lessons-dialog" onClose={onClose}>
    <header><div><BookOpenCheck size={17} /><strong>{text('Research review', '研究审核')}</strong></div><button data-dialog-dismiss onClick={onClose} title={text('Close', '关闭')} aria-label={text('Close', '关闭')}><X size={15} /></button></header>
    <nav className="review-tabs" role="tablist">{tabs.map((item) => <button key={item.key} role="tab" aria-selected={tab === item.key} className={tab === item.key ? 'primary' : ''} onClick={() => setTab(item.key)}>{item.label}</button>)}</nav>
    {tab === 'labels' ? <BranchLabelPanel request={request} taskId={taskId} /> : tab === 'policies' ? <PolicyPanel request={request} taskId={taskId} /> : <>
    <p className="lessons-intro">{text('Lessons are short, human-approved notes distilled from past research trees. Coordinator lessons join its guidance; Expert lessons are read only when relevant. Nothing is added without your approval.', '经验是从以往研究树中提炼、并经你批准的简短说明。协调者经验加入其指导；专家经验仅在相关时读取。未经你批准不会加入任何经验。')}</p>
    <div className="lessons-actions">
      <button disabled={busy} onClick={() => consolidate(false)}><RefreshCw size={14} />{text('Clean up records', '清理记录')}</button>
      <button disabled={busy} className="primary" onClick={() => consolidate(true)}><Sparkles size={14} />{text('Clean up and propose lessons', '清理并生成经验提议')}</button>
      {busy ? <LoaderCircle className="spin" size={16} /> : null}
    </div>
    {notice ? <p className="lessons-notice" role="status">{notice}</p> : null}
    {overview ? <>
      <section aria-label={text('Pending proposals', '待审核提议')}>
        <h3>{text(`Pending proposals (${overview.pending.length})`, `待审核提议（${overview.pending.length}）`)}</h3>
        {overview.pending.length ? overview.pending.map((proposal) => <ProposalCard key={proposal.id} proposal={proposal} overview={overview} busy={busy} onDecide={(item, decision, draft, reason) => send('research.lessons.decide', decisionPayload(item, decision, draft, reason))} />)
          : <p className="lessons-empty">{text('No proposals waiting. Run "Clean up and propose lessons" after a few research tasks.', '暂无待审核提议。完成若干研究任务后可点击“清理并生成经验提议”。')}</p>}
      </section>
      {roles.map(({key, title}) => {
        const lessons = overview.active.filter((lesson) => lesson.role === key);
        return <section key={key} aria-label={title}>
          <h3>{title} <small>{lessons.length}/{overview.limits.max_active_per_role}</small></h3>
          {lessons.length ? <ul className="lesson-active-list">{lessons.map((lesson) => <ActiveLessonRow key={lesson.id} lesson={lesson} busy={busy} onRetire={(item, reason) => send('research.lessons.retire', {lesson_id: item.id, reason})} />)}</ul>
            : <p className="lessons-empty">{text('None active.', '暂无生效经验。')}</p>}
        </section>;
      })}
      <footer className="lessons-footer"><small>{text(`${overview.digests} task digests · lessons version ${overview.lessonsVersion ?? 'none'} · last cleanup ${overview.lastConsolidatedAt ? new Date(overview.lastConsolidatedAt).toLocaleString() : 'never'}`, `${overview.digests} 个任务摘要 · 经验版本 ${overview.lessonsVersion ?? '无'} · 上次清理 ${overview.lastConsolidatedAt ? new Date(overview.lastConsolidatedAt).toLocaleString() : '从未'}`)}</small></footer>
    </> : busy ? null : <p className="lessons-empty">{text('Open a project to review its lessons.', '请先打开项目以审核其经验。')}</p>}
    </>}
  </ModalDialog>;
}

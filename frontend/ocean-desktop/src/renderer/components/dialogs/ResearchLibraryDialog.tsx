import {useCallback, useEffect, useState} from 'react';
import {BookOpenCheck, Check, LoaderCircle, RefreshCw, X} from 'lucide-react';

import {useUiLanguage} from '../../i18n.js';
import {markPayload, parseLibrary, summarizeUpdate, type EvidenceTask, type Lesson, type Library, type LibraryChange, type Mark, type Tool} from '../../research-library.js';
import type {EventPayload} from '../../types.js';
import {ModalDialog} from './ModalDialog.js';

export type LibraryRequest = (
  type: string,
  payload: EventPayload,
  onResult: (result: EventPayload) => void,
  onError: (message: string) => void,
) => void;

/** The owner's two choices for one item: right keeps it, wrong removes it. */
function MarkButtons({human, busy, onMark}: {human: Mark | null; busy: boolean; onMark: (verdict: Mark) => void}): React.JSX.Element {
  const {text} = useUiLanguage();
  return <div className="library-marks">
    <button disabled={busy || human === 'right'} className={human === 'right' ? 'primary' : ''} aria-pressed={human === 'right'} title={text('Right: keep it, whatever later tasks show', '对：一直保留，不受之后任务的影响')} onClick={() => onMark('right')}><Check size={14} />{text('Right', '对')}</button>
    <button disabled={busy || human === 'wrong'} className={human === 'wrong' ? 'danger' : ''} aria-pressed={human === 'wrong'} title={text('Wrong: remove it and do not propose it again', '错：移除，并且不再提出')} onClick={() => onMark('wrong')}><X size={14} />{text('Wrong', '错')}</button>
  </div>;
}

function EvidenceList({tasks, label}: {tasks: EvidenceTask[]; label: string}): React.JSX.Element | null {
  if (!tasks.length) return null;
  return <details className="lesson-evidence"><summary>{label} ({tasks.length})</summary><ul>{tasks.map((task) => <li key={task.task_key}><code>{task.task_key.slice(0, 8)}</code> {task.question || '—'}</li>)}</ul></details>;
}

function LessonRow({lesson, busy, onMark}: {lesson: Lesson; busy: boolean; onMark: (verdict: Mark) => void}): React.JSX.Element {
  const {text} = useUiLanguage();
  const {supporting, counter} = lesson.evidence_tasks;
  return <li className="lesson-active">
    <div>
      <strong>{lesson.id}</strong> {lesson.text}{lesson.active && !lesson.shown ? <> <span className="lesson-kind">{text('Kept, not shown to tasks now', '已保留，目前不展示给任务')}</span></> : null}<br />
      <small>{text('Applies when', '适用条件')}: {lesson.applies_when}</small><br />
      <small>{lesson.active
        ? text(`Shown in ${lesson.tasksShown} tasks, named in ${lesson.tasksCited}`, `在 ${lesson.tasksShown} 个任务中展示，被引用 ${lesson.tasksCited} 次`)
        : `${text('Removed', '已移除')}: ${lesson.retiredReason || '—'}`}</small>
      <EvidenceList tasks={supporting} label={text('Supporting tasks', '支持的任务')} />
      <EvidenceList tasks={counter} label={text('Counterexamples', '反例')} />
    </div>
    <MarkButtons human={lesson.human} busy={busy} onMark={onMark} />
  </li>;
}

function ToolRow({tool, busy, onMark}: {tool: Tool; busy: boolean; onMark: (verdict: Mark) => void}): React.JSX.Element {
  const {text} = useUiLanguage();
  const state = tool.shown ? null : tool.learned ? text('Removed', '已移除') : text('Not listed in the skill (still importable)', '未列入技能（仍可导入）');
  return <li className="lesson-active">
    <div>
      <code>ao.{tool.signature}</code> <span className="lesson-kind">{tool.learned ? text('Learned', '学到的') : text('Built in', '内置')}</span><br />
      {tool.summary}<br />
      <small>{tool.tasks
        ? text(`Called in ${tool.tasksCalled} of ${tool.tasks} tasks, ${tool.calls} calls`, `${tool.tasks} 个任务中有 ${tool.tasksCalled} 个调用过，共 ${tool.calls} 次`)
        : text('No task recorded yet', '还没有任务记录')}{state ? ` · ${state}${tool.reason ? `: ${tool.reason}` : ''}` : ''}</small>
      {tool.code ? <details className="lesson-evidence"><summary>{text('Code and test', '代码与测试')}</summary><pre className="library-code">{tool.code}</pre><pre className="library-code">{tool.test}</pre></details> : null}
    </div>
    <MarkButtons human={tool.human} busy={busy} onMark={onMark} />
  </li>;
}

function ChangeList({changes}: {changes: LibraryChange[]}): React.JSX.Element | null {
  const {text} = useUiLanguage();
  if (!changes.length) return null;
  return <details className="lesson-evidence library-changes"><summary>{text('Recent changes', '最近的变更')} ({changes.length})</summary><ul>{changes.map((change, index) => <li key={`${change.at}-${change.item}-${index}`}>
    {change.at ? new Date(change.at).toLocaleString() : ''} · <code>{change.item}</code> {change.change} · {change.by}{change.reason ? ` — ${change.reason}` : ''}
  </li>)}</ul></details>;
}

export function ResearchLibraryDialog({open, onClose, request}: {
  open: boolean;
  onClose: () => void;
  request: LibraryRequest;
}): React.JSX.Element | null {
  const {text} = useUiLanguage();
  const [tab, setTab] = useState<'lessons' | 'tools'>('lessons');
  const [library, setLibrary] = useState<Library | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const fail = useCallback((message: string) => {setNotice(message); setBusy(false);}, []);
  const send = useCallback((kind: 'get' | 'update' | 'mark', payload: EventPayload, after?: (result: EventPayload) => void) => {
    setBusy(true); setNotice(null);
    request(`research.library.${kind}`, payload, (result) => {
      const next = parseLibrary(result);
      if (next) setLibrary(next);
      setBusy(false);
      after?.(result);
    }, fail);
  }, [fail, request]);

  useEffect(() => {if (open) send('get', {});}, [open, send]);
  if (!open) return null;

  const report = (result: EventPayload) => {
    const done = summarizeUpdate(result);
    if (!done) return;
    const needed = library?.minSupport ?? 3;
    if (!done.reviewed) {setNotice(text('No research task finished since the last update.', '上次更新之后没有新完成的研究任务。')); return;}
    // Lessons and tools ask for different numbers of questions, so the tools are always reported.
    const few = done.questions !== null && done.questions < needed
      ? text(`Lessons need finished tasks on at least ${needed} different questions; this project has ${done.questions}. `, `经验需要至少 ${needed} 个不同问题的已完成任务；当前项目只有 ${done.questions} 个。`)
      : '';
    const left = done.tasksLeft
      ? text(` ${done.tasksLeft} finished tasks did not fit this review; the next update reads them first.`, `还有 ${done.tasksLeft} 个已完成的任务这次没读到，下次更新会先读它们。`)
      : '';
    setNotice(few + text(
      `${done.lessonChanges} lesson changes; tools added: ${done.toolsAdded.join(', ') || 'none'}; tools taken off the list: ${done.toolsRemoved.join(', ') || 'none'}; ${done.refused} proposals refused by the rules.`,
      `经验变更 ${done.lessonChanges} 条；新增工具：${done.toolsAdded.join('、') || '无'}；移出清单的工具：${done.toolsRemoved.join('、') || '无'}；${done.refused} 条提议未通过规则。`) + left);
  };
  const update = () => {
    send('update', {review: true}, report);
    // The backend runs the update beside its other work and replies when it is done.
    setNotice(text('Reviewing the finished tasks. This can take several minutes; you can close this dialog and keep working.', '正在审查已完成的任务，可能需要几分钟；可以关闭这个对话框继续使用。'));
  };
  const markItem = (kind: 'lesson' | 'tool', id: string) => (verdict: Mark) => send('mark', markPayload(kind, id, verdict));

  const lessonCount = library?.skills.reduce((total, skill) => total + skill.lessons.length, 0) ?? 0;
  const tabs = [
    {key: 'lessons', label: text(`Lessons (${lessonCount})`, `经验（${lessonCount}）`)},
    {key: 'tools', label: text(`Tools (${library?.tools.filter((tool) => tool.shown).length ?? 0})`, `工具（${library?.tools.filter((tool) => tool.shown).length ?? 0}）`)},
  ] as const;
  const readers = {coordinator: text('read by the Coordinator', '协调者阅读'), expert: text('read by the Experts', '专家阅读')};

  return <ModalDialog ariaLabel={text('Lessons and tools', '经验与工具')} className="lessons-dialog" onClose={onClose}>
    <header><div><BookOpenCheck size={17} /><strong>{text('Lessons and tools', '经验与工具')}</strong></div><button data-dialog-dismiss onClick={onClose} title={text('Close', '关闭')} aria-label={text('Close', '关闭')}><X size={15} /></button></header>
    <p className="lessons-intro">{text('OceanX learns from finished research tasks. Lessons are short notes written into the skills its agents read; tools are helper functions their analysis code can call. Both take effect without approval. Mark an item right to keep it, or wrong to remove it.', 'OceanX 会从已完成的研究任务中学习。经验是写入各角色技能里的简短说明；工具是分析代码可以调用的辅助函数。两者无需批准即生效。把一条标为“对”会一直保留，标为“错”会移除。')}</p>
    <div className="lessons-actions">
      <button disabled={busy} className="primary" title={text('Review the finished tasks now (uses the model). OceanX also does this by itself, at most once a day.', '现在审查已完成的任务（会调用模型）。系统也会自动进行，最多每天一次。')} onClick={update}><RefreshCw size={14} />{text('Update now', '立即更新')}</button>
      {busy ? <LoaderCircle className="spin" size={16} /> : null}
    </div>
    {notice ? <p className="lessons-notice" role="status">{notice}</p> : null}
    {library ? <>
      <nav className="review-tabs" role="tablist">{tabs.map((item) => <button key={item.key} role="tab" aria-selected={tab === item.key} className={tab === item.key ? 'primary' : ''} onClick={() => setTab(item.key)}>{item.label}</button>)}</nav>
      {tab === 'lessons' ? <>
        {lessonCount ? library.skills.filter((skill) => skill.lessons.length).map((skill) => <section key={skill.name} aria-label={skill.name}>
          <h3><code>{skill.name}</code> <small>{text(`${skill.lessons.length} lessons, a task is shown up to ${skill.limit}`, `${skill.lessons.length} 条，每个任务最多展示 ${skill.limit} 条`)} · {readers[skill.reader]}</small></h3>
          <ul className="lesson-active-list">{skill.lessons.map((lesson) => <LessonRow key={lesson.id} lesson={lesson} busy={busy} onMark={markItem('lesson', lesson.id)} />)}</ul>
        </section>) : <p className="lessons-empty">{text(`No lessons yet. They need finished research tasks on at least ${library.minSupport} different questions.`, `还没有经验。需要至少 ${library.minSupport} 个不同问题的已完成研究任务。`)}</p>}
        {library.retired.length ? <section aria-label={text('Removed lessons', '已移除的经验')}>
          <details><summary>{text(`Removed lessons (${library.retired.length})`, `已移除的经验（${library.retired.length}）`)}</summary>
            <ul className="lesson-active-list">{library.retired.map((lesson) => <LessonRow key={lesson.id} lesson={lesson} busy={busy} onMark={markItem('lesson', lesson.id)} />)}</ul>
          </details>
        </section> : null}
        <section><ChangeList changes={library.changes.filter((change) => change.kind === 'lesson')} /></section>
      </> : <>
        <section aria-label={text('Tools', '工具')}>
          <ul className="lesson-active-list">{library.tools.map((tool) => <ToolRow key={tool.name} tool={tool} busy={busy} onMark={markItem('tool', tool.name)} />)}</ul>
        </section>
        <section><ChangeList changes={library.changes.filter((change) => change.kind === 'tool')} /></section>
      </>}
      <footer className="lessons-footer"><small>{text(`${library.digests} task records · version ${library.version ?? 'none'} · last review ${library.lastReviewedAt ? new Date(library.lastReviewedAt).toLocaleString() : 'never'}`, `${library.digests} 条任务记录 · 版本 ${library.version ?? '无'} · 上次审查 ${library.lastReviewedAt ? new Date(library.lastReviewedAt).toLocaleString() : '从未'}`)}</small></footer>
    </> : busy ? null : <p className="lessons-empty">{text('Open a project to see what it has learned.', '请先打开项目，查看它学到的内容。')}</p>}
  </ModalDialog>;
}

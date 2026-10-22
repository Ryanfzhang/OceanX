import {useEffect, useState} from 'react';
import {LoaderCircle, Plus, Settings, Trash2} from 'lucide-react';
import type {ProjectCatalogEntry} from '../../ocean-desktop/src/renderer/project-catalog.js';
import {useUiLanguage} from '../../ocean-desktop/src/renderer/i18n.js';

type Props = {
  projects: ProjectCatalogEntry[];
  activeProjectPath: string | null;
  activeTaskId: string | null;
  onNewTask: (path: string) => void;
  onOpenTask: (path: string, taskId: string) => void;
  onDeleteTask: (path: string, taskId: string) => void;
  onOpenSettings: () => void;
};

export function ProjectTaskSidebar({projects, activeProjectPath, activeTaskId, onNewTask, onOpenTask, onDeleteTask, onOpenSettings}: Props): React.JSX.Element {
  const {text} = useUiLanguage();
  const project = projects.find(p => p.path === activeProjectPath) ?? projects[0];
  const [seen, setSeen] = useState<Record<string, number>>({});
  useEffect(() => {
    const task = project?.tasks.find(t => t.task_id === activeTaskId);
    if (task) setSeen(current => current[task.task_id] === task.task_revision ? current : {...current, [task.task_id]: task.task_revision});
  }, [project, activeTaskId]);
  return <aside className="task-sidebar web-task-sidebar">
    <div className="window-drag" />
    <div className="sidebar-brand"><span className="sidebar-brand-mark"><span /><span /><span /></span><strong>OceanX</strong></div>
    <div className="project-list-heading"><span>{text('Tasks', '任务')}</span><button type="button" className="web-new-task" disabled={!project} onClick={() => project && onNewTask(project.path)} title={text('New task', '新建任务')} aria-label={text('New task', '新建任务')}><Plus size={17} /></button></div>
    <nav className="project-list web-task-list" aria-label={text('Research tasks', '研究任务')}>
      {project?.tasks.filter(t => t.status !== 'archived').map(task => {
        const running = Boolean(task.active_request_id) || ['planning', 'working'].includes(task.workflow?.state ?? '');
        const active = task.task_id === activeTaskId;
        const unread = !active && !running && task.task_revision > (seen[task.task_id] ?? 0);
        return <div className={`task-row${active ? ' active' : ''}${running ? ' running' : unread ? ' unread' : ' read'}`} key={task.task_id}>
          <button type="button" onClick={() => {setSeen(s => ({...s, [task.task_id]: task.task_revision})); onOpenTask(project.path, task.task_id);}} title={task.title}>{task.title}</button>
          {running || unread ? <span className={`task-runtime-status ${running ? 'running' : 'complete'}`} role="img" aria-label={running ? text('Task is running', '任务运行中') : text('Task has unread results', '任务有未查看结果')}>{running ? <LoaderCircle className="spin" size={16} /> : <i aria-hidden="true" />}</span> : null}
          <button type="button" className="task-delete" onClick={() => onDeleteTask(project.path, task.task_id)} title={text('Delete task', '删除任务')} aria-label={`${text('Delete', '删除')} ${task.title}`}><Trash2 size={14} /></button>
        </div>;
      })}
      {!project?.tasks.length ? <small className="project-empty">{text('No research tasks yet', '还没有研究任务')}</small> : null}
    </nav>
    <footer><button type="button" onClick={onOpenSettings}><Settings size={16} />{text('Settings', '设置')}</button></footer>
  </aside>;
}

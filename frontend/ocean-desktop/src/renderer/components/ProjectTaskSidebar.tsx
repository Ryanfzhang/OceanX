import {useCallback, useEffect, useState} from 'react';
import {BookOpenCheck, Folder, LoaderCircle, Plus, Settings, Trash2} from 'lucide-react';

import type {ProjectCatalogEntry} from '../project-catalog.js';
import {useUiLanguage} from '../i18n.js';

const TASK_SEEN_REVISIONS_KEY = 'oceanx.task-seen-revisions.v1';

function taskSeenKey(projectPath: string, taskId: string): string {
  return JSON.stringify([projectPath, taskId]);
}

function readSeenRevisions(): Record<string, number> {
  if (typeof window === 'undefined') return {};
  try {
    const value = JSON.parse(window.localStorage.getItem(TASK_SEEN_REVISIONS_KEY) ?? '{}') as unknown;
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    return Object.fromEntries(Object.entries(value).filter((entry): entry is [string, number] => (
      Number.isInteger(entry[1]) && Number(entry[1]) >= 0
    )));
  } catch {
    return {};
  }
}

function persistSeenRevisions(value: Record<string, number>): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(TASK_SEEN_REVISIONS_KEY, JSON.stringify(value));
  } catch {
    // A restricted storage context should not prevent task navigation.
  }
}

export function ProjectTaskSidebar({
  projects,
  activeProjectPath,
  activeTaskId,
  onNewTask,
  onChooseProject,
  onOpenProject,
  onRemoveProject,
  onOpenTask,
  onDeleteTask,
  onOpenSettings,
  onOpenLessons,
  pendingLessons = 0,
}: {
  projects: ProjectCatalogEntry[];
  activeProjectPath: string | null;
  activeTaskId: string | null;
  onNewTask: (projectPath: string) => void;
  onChooseProject: () => void;
  onOpenProject: (projectPath: string) => void;
  onRemoveProject: (project: ProjectCatalogEntry) => void;
  onOpenTask: (projectPath: string, taskId: string) => void;
  onDeleteTask: (projectPath: string, taskId: string) => void;
  onOpenSettings: () => void;
  onOpenLessons?: () => void;
  pendingLessons?: number;
}): React.JSX.Element {
  const {text} = useUiLanguage();
  const [seenRevisions, setSeenRevisions] = useState<Record<string, number>>(readSeenRevisions);
  const markViewed = useCallback((projectPath: string, taskId: string, revision: number) => {
    const key = taskSeenKey(projectPath, taskId);
    setSeenRevisions((current) => {
      if ((current[key] ?? -1) >= revision) return current;
      const next = {...current, [key]: revision};
      persistSeenRevisions(next);
      return next;
    });
  }, []);

  useEffect(() => {
    if (!activeProjectPath || !activeTaskId) return;
    const task = projects
      .find((project) => project.path === activeProjectPath)
      ?.tasks.find((candidate) => candidate.task_id === activeTaskId);
    if (task) markViewed(activeProjectPath, activeTaskId, task.task_revision);
  }, [activeProjectPath, activeTaskId, markViewed, projects]);

  return <aside className="task-sidebar">
    <div className="window-drag" />
    <div className="sidebar-brand"><span className="sidebar-brand-mark"><span /><span /><span /></span><strong>OceanX</strong></div>
    <div className="project-list-heading">
      <span>{text('Projects', '项目')}</span>
      <button className="add-project" type="button" onClick={onChooseProject} title={text('Add local project', '添加本地项目')} aria-label={text('Add local project', '添加本地项目')}>
        <Plus size={14} />
      </button>
    </div>
    <nav className="project-list" aria-label="Projects and research tasks">
      {projects.length ? projects.map((project) => <section className={`project-group${project.path === activeProjectPath ? ' active' : ''}`} key={project.path}>
        <div className="project-heading-row">
          <button className="project-row" type="button" onClick={() => onOpenProject(project.path)} title={project.path}>
            <Folder size={16} />
            <strong>{project.name}</strong>
          </button>
          <div className="project-actions">
            <button
              className="project-new-task"
              type="button"
              onClick={() => onNewTask(project.path)}
              title={text(`New task in ${project.name}`, `在 ${project.name} 中新建任务`)}
              aria-label={text(`New task in ${project.name}`, `在 ${project.name} 中新建任务`)}
            >
              <Plus size={14} />
            </button>
            <button
              className="project-delete"
              type="button"
              onClick={() => onRemoveProject(project)}
              title={text(`Remove ${project.name}`, `移除 ${project.name}`)}
              aria-label={text(`Remove project ${project.name}`, `移除项目 ${project.name}`)}
            ><Trash2 size={12} /></button>
          </div>
        </div>
        <div className="project-tasks">
          {project.tasks.length ? project.tasks.map((task) => {
            const running = Boolean(task.active_request_id)
              || task.workflow?.state === 'planning'
              || task.workflow?.state === 'working';
            const active = task.task_id === activeTaskId && project.path === activeProjectPath;
            const unread = !active && !running
              && task.task_revision > (seenRevisions[taskSeenKey(project.path, task.task_id)] ?? 0);
            return <div className={`task-row${active ? ' active' : ''}${running ? ' running' : unread ? ' unread' : ' read'}`} key={task.task_id}>
              <button type="button" onClick={() => {
                markViewed(project.path, task.task_id, task.task_revision);
                onOpenTask(project.path, task.task_id);
              }} title={task.title}>{task.title}</button>
              {running || unread ? <span
                className={`task-runtime-status ${running ? 'running' : 'complete'}`}
                role="img"
                aria-label={running ? text('Task is running', '任务运行中') : text('Task has unread results', '任务有未查看结果')}
                title={running ? text('Task is running', '任务运行中') : text('Task has unread results', '任务有未查看结果')}
              >
                {running ? <LoaderCircle className="spin" size={16} strokeWidth={2.2} /> : <i aria-hidden="true" />}
              </span> : null}
              <button type="button" className="task-delete" onClick={() => onDeleteTask(project.path, task.task_id)} title={text('Delete task', '删除任务')} aria-label={`${text('Delete', '删除')} ${task.title}`}><Trash2 size={14} /></button>
            </div>;
          }) : <small className="project-empty">{text('No research tasks yet', '还没有研究任务')}</small>}
        </div>
      </section>) : <div className="project-list-empty"><Folder size={20} /><p>{text('Add a local project to keep its research tasks here.', '添加一个本地项目后，研究任务会显示在这里。')}</p></div>}
    </nav>
    <footer><button type="button" onClick={onOpenSettings}><Settings size={16} />{text('Settings', '设置')}</button>{onOpenLessons ? <button type="button" onClick={onOpenLessons} disabled={!activeProjectPath} title={text('Review lessons, branch labels and policies', '审核经验、分支标注与策略')}><BookOpenCheck size={16} />{text('Review', '审核')}{pendingLessons > 0 ? <span className="lessons-badge" aria-label={text(`${pendingLessons} pending`, `${pendingLessons} 条待审核`)}>{pendingLessons}</span> : null}</button> : null}</footer>
  </aside>;
}

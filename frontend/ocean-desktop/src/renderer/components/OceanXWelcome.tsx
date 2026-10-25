import {ArrowUp, BookOpen, Database, Folder, FolderOpen, RefreshCw, X} from 'lucide-react';

import iconUrl from '../assets/brand/oceanx-icon.svg';
import darkIconUrl from '../assets/brand/oceanx-icon-dark.svg';
import coreLogoUrl from '../assets/core-hkust-logo.png';
import type {WorkspaceSourceKind} from '../../shared/bridge.js';
import {useUiLanguage} from '../i18n.js';
import {SourceMenu} from './SourceMenu.js';

const CORE_HOME_URL = 'https://core-hkmacau.hkust.edu.hk/';

export function OceanXWelcome({
  projectName,
  hasProject,
  title,
  onTitle,
  onCreateTask,
  onChooseProject,
  pendingSources = [],
  sourceBusy = false,
  onAddSource,
  onRemoveSource,
}: {
  projectName: string;
  hasProject: boolean;
  title: string;
  onTitle: (value: string) => void;
  onCreateTask: () => void;
  onChooseProject: () => void;
  /** Names of the PDFs and data folders added before the task exists; they are imported once it is created. */
  pendingSources?: string[];
  sourceBusy?: boolean;
  onAddSource?: (kind: WorkspaceSourceKind) => void;
  onRemoveSource?: (index: number) => void;
}): React.JSX.Element {
  const {text} = useUiLanguage();
  const entryPoints = [
    {
      kind: 'papers',
      label: text('Find and review papers', '检索与阅读论文'),
      icon: <BookOpen size={20} aria-hidden="true" />,
    },
    {
      kind: 'data',
      label: text('Analyze data', '分析数据'),
      icon: <Database size={20} aria-hidden="true" />,
    },
    {
      kind: 'autoresearch',
      label: text('Run Autoresearch', '开展 Autoresearch'),
      icon: <RefreshCw size={20} aria-hidden="true" />,
    },
  ] as const;
  return <section className="ocean-welcome" aria-label="Welcome to OceanX">
    <a
      className="welcome-ack"
      href={CORE_HOME_URL}
      target="_blank"
      rel="noreferrer noopener"
      title={text('Center for Ocean Research in Hong Kong and Macau (CORE), HKUST', '港澳海洋研究中心（CORE）· 香港科技大学')}
    >
      <img src={coreLogoUrl} alt={text('CORE · HKUST', '港澳海洋研究中心 · 香港科技大学')} />
      <span>{text('Supported by CORE, HKUST', '感谢港澳海洋研究中心（CORE）支持')}</span>
    </a>
    <div className="ocean-welcome-greeting">
      <img className="light" src={iconUrl} alt="" />
      <img className="dark" src={darkIconUrl} alt="" />
      <h1 className="ocean-welcome-question">{text('What would you like to do with OceanX?', '你想用 OceanX 做什么？')}</h1>
    </div>
    {hasProject ? <>
      <div className="welcome-entry-points" aria-label={text('Research starting points', '研究入口')}>
        {entryPoints.map((entry) => <article
          className={`welcome-entry-point ${entry.kind}`}
          key={entry.kind}
        >
          {entry.icon}
          <span>{entry.label}</span>
        </article>)}
      </div>
      <div className="welcome-task-entry">
        <form onSubmit={(event) => {event.preventDefault(); onCreateTask();}}>
          <input
            id="welcome-task-title"
            value={title}
            onChange={(event) => onTitle(event.target.value)}
            placeholder={text('Name this research task', '给这项研究起个名字')}
            aria-label={text('Research task name', '研究任务名称')}
            autoFocus
          />
          <div className="welcome-task-actions">
            {onAddSource ? <SourceMenu placement="down" busy={sourceBusy} onChoose={onAddSource} /> : null}
            <span className="welcome-project" title={projectName}><Folder size={14} aria-hidden="true" />{projectName}</span>
            {pendingSources.length ? <div className="welcome-sources">
              {pendingSources.map((name, index) => <span className="welcome-source" key={`${name}:${index}`} title={name}>
                <span>{name}</span>
                {onRemoveSource ? <button type="button" onClick={() => onRemoveSource(index)} aria-label={`${text('Remove', '移除')} ${name}`}><X size={12} /></button> : null}
              </span>)}
            </div> : null}
            <button className="send-button" type="submit" disabled={!title.trim() || sourceBusy} title={text('Create research task', '创建研究任务')} aria-label={text('Create research task', '创建研究任务')}><ArrowUp size={17} /></button>
          </div>
        </form>
      </div>
    </> : <button type="button" className="welcome-open-project" onClick={onChooseProject}><FolderOpen size={18} />{text('Choose a local project', '选择一个本地项目')}</button>}
  </section>;
}

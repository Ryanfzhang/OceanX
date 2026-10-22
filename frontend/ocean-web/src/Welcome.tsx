import {SendHorizontal} from 'lucide-react';
import {useUiLanguage} from '../../ocean-desktop/src/renderer/i18n.js';

type Props = {hasProject: boolean; title: string; onTitle: (value: string) => void; onCreateTask: () => void};
export function OceanXWelcome({hasProject, title, onTitle, onCreateTask}: Props): React.JSX.Element {
  const {text} = useUiLanguage();
  return <section className="ocean-welcome" aria-label="Welcome to OceanX">
    <h1 className="ocean-welcome-question">{text('What would you like to research?', '你想研究什么？')}</h1>
    <p className="web-welcome-note">{text('Create a task, then attach data or a paper using its server path.', '新建任务后，可以填写服务器路径添加数据或论文。')}</p>
    <div className="welcome-task-entry"><form onSubmit={event => {event.preventDefault(); onCreateTask();}}>
      <input id="welcome-task-title" value={title} onChange={event => onTitle(event.target.value)} aria-label={text('Research task name', '研究任务名称')} placeholder={text('Name this research task', '给这项研究起个名字')} autoFocus />
      <button type="submit" disabled={!hasProject || !title.trim()} title="Create research task"><SendHorizontal size={18} /></button>
    </form></div>
  </section>;
}

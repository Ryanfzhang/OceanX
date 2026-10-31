import {renderToStaticMarkup} from 'react-dom/server';
import {expect, it} from 'vitest';
import {ProjectTaskSidebar} from './ProjectTaskSidebar.js';

it('keeps stopped tasks in history without a running indicator, even with an old working workflow', () => {
  const markup = renderToStaticMarkup(<ProjectTaskSidebar
    projects={[{path: '/project', name: 'Project', lastOpenedAt: 0, tasks: [
      {task_id: 'stopped', workspace_id: 'ws', title: 'Stopped paper', status: 'active', task_revision: 2,
        active_request_id: null, workflow: {request_id: 'old', state: 'working', activity: 'Running code'}},
      {task_id: 'running', workspace_id: 'ws', title: 'Live paper', status: 'active', task_revision: 1,
        active_request_id: 'req_live'},
    ]}]} activeProjectPath="/project" activeTaskId="stopped" onNewTask={() => {}}
    onChooseProject={() => {}} onOpenProject={() => {}} onRemoveProject={() => {}}
    onOpenTask={() => {}} onDeleteTask={() => {}} onOpenSettings={() => {}}
  />);
  expect(markup).toContain('Stopped paper');
  expect(markup.match(/aria-label="Task is running"/g)).toHaveLength(1);
  const stoppedRow = markup.slice(markup.indexOf('title="Stopped paper"'), markup.indexOf('title="Live paper"'));
  expect(stoppedRow).not.toContain('aria-label="Task is running"');
});

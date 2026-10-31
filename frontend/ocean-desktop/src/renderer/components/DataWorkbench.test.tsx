import {renderToStaticMarkup} from 'react-dom/server';
import {expect, it} from 'vitest';

import type {TaskResultRecord} from '../types.js';
import {DataWorkbench} from './DataWorkbench.js';
import {ConversationTranscript} from './ConversationTranscript.js';

it('renders CSV cells as text, preserves formatting, and offers the original download', () => {
  const markup = renderToStaticMarkup(<DataWorkbench document={{key: 'table', title: 'metrics.csv', content: {
    data_file: 'metrics.csv', columns: ['site', 'value'], rows: [['<script>alert(1)</script>', '001'], ['a,b', 'line 1\nline 2']], truncated: true,
  }}} loading={false} error={null} downloadUrl="/resource/csv" onClose={() => {}} />);
  expect(markup).toContain('first 200 rows');
  expect(markup).toContain('<th scope="col">site</th>');
  expect(markup).toContain('<td>001</td>');
  expect(markup).toContain('line 1\nline 2');
  expect(markup).not.toContain('<script>');
  expect(markup).toContain('href="/resource/csv"');
});

it('shows NetCDF metadata without offering any download', () => {
  const markup = renderToStaticMarkup(<DataWorkbench document={{key: 'array', title: 'response.nc', content: {
    data_file: 'response.nc', columns: ['Variable', 'Dimensions'], rows: [['temperature', 'time, depth']],
  }}} loading={false} error={null} downloadUrl="/resource/nc" onClose={() => {}} />);
  expect(markup).toContain('Variables and dimensions');
  expect(markup).toContain('temperature');
  expect(markup).not.toContain('href=');
});

it('binds saved bracket references to CSV and extensionless NetCDF results', () => {
  const records: TaskResultRecord[] = ['metrics.csv', 'response.nc'].map((name, index) => ({
    result_ref: {task_id: 'task', result_id: `data_${index}`, version: 1}, workspace_id: 'ws',
    kind: index ? 'file' : 'table', title: name, summary: '', created_at: '2026-10-27T10:01:00Z',
    execution_output_names: [`single/${name}`, ...(index ? ['single/response'] : [])],
    content: {role: 'output_data', result_key: `single/${name}`, data_file: name},
    files: [{path: name, mime_type: index ? 'application/x-netcdf' : 'text/csv', size: 10, sha256: 'a'.repeat(64)}],
  }));
  const markup = renderToStaticMarkup(<ConversationTranscript
    loading={false} transcript={[
      {item_id: 'u', role: 'user', text: 'Analyse.', request_id: 'req', created_at: '2026-10-27T10:00:00Z'},
      {item_id: 'a', role: 'assistant', text: 'Tables [single/metrics.csv] and arrays [single/response].', request_id: 'req', created_at: '2026-10-27T10:02:00Z'},
    ]} streaming="" activeRequestId={null} task={null} workspacePath="/tmp/workspace" outputs={[]}
    manifests={[]} taskResults={records} team={null} onOpenResult={() => {}} onOpenTaskResult={() => {}}
  />);
  expect(markup).not.toContain('[single/metrics.csv]');
  expect(markup).not.toContain('[single/response]');
  expect(markup).toContain('metrics.csv');
  expect(markup).toContain('markdown-result-link');
});

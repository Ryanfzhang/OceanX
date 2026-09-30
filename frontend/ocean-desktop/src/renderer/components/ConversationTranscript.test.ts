import {expect, it} from 'vitest';

import type {TaskResultRecord, TranscriptItem} from '../types.js';
import {chronologicalResearchLog, resultOwnerDisplayAliases, taskResultKeys} from './ConversationTranscript.js';

it('resolves durable task result references with or without a version', () => {
  const result = {
    result_ref: {task_id: 'task_1', result_id: 'result_2', version: 1},
    content: {
      output_path: 'outputs/temperature_section.nc',
      result_key: 'ocean-process-1/temperature_section',
    },
  } as unknown as TaskResultRecord;

  expect(taskResultKeys(result)).toEqual(expect.arrayContaining([
    'task_1/result_2@v1',
    'task_1/result_2@v0001',
    'task_1/result_2',
    'result_2@v1',
    'result_2',
    'ocean-process-1/temperature_section',
    'outputs/temperature_section.nc',
  ]));
});

it('uses research nodes when available and role ordinals for ordinary tasks', () => {
  const researchAliases = resultOwnerDisplayAliases({
    revision: 1,
    status: 'completed',
    strategy: 'parallel_team',
    agents: [
      {agent_id: 'coordinator', semantic_role: 'Coordinator', authority: 'coordinator', status: 'completed', activity: ''},
      {agent_id: 'ocean-a', expert_key: 'ocean-a', profile_id: 'ocean_process_expert', semantic_role: 'Ocean Expert', authority: 'expert', status: 'completed', activity: ''},
    ],
    todos: [{todo_id: 'todo-a', question: 'B1.1: test the mechanism.', depends_on: [], profile_id: 'ocean_process_expert', expert_key: 'ocean-a', expected_outputs: [], state: 'result_returned'}],
    dependencies: [],
    interactions: [],
  });
  expect(researchAliases.get('ocean-a')).toBe('B1.1');

  const standardAliases = resultOwnerDisplayAliases({
    revision: 1,
    status: 'completed',
    strategy: 'parallel_team',
    agents: [
      {agent_id: 'coordinator', semantic_role: 'Coordinator', authority: 'coordinator', status: 'completed', activity: ''},
      {agent_id: 'ocean-a', profile_id: 'ocean_process_expert', semantic_role: 'Ocean Expert', authority: 'expert', status: 'completed', activity: ''},
      {agent_id: 'ocean-b', profile_id: 'ocean_process_expert', semantic_role: 'Ocean Expert', authority: 'expert', status: 'completed', activity: ''},
    ],
    dependencies: [],
    interactions: [],
  });
  expect(standardAliases.get('ocean-a')).toBe('Ocean 1');
  expect(standardAliases.get('ocean-b')).toBe('Ocean 2');
});

it('interleaves Coordinator updates and Expert results by their actual timestamps', () => {
  const process = [
    {item_id: 'coordinator-early', role: 'assistant', text: 'Started', created_at: '2026-09-17T11:00:00Z'},
    {item_id: 'coordinator-late', role: 'assistant', text: 'Followed up', created_at: '2026-09-17T11:20:00Z'},
  ] as TranscriptItem[];
  const entries = chronologicalResearchLog(process, [{
    agent: {
      agent_id: 'expert-1', semantic_role: 'Ocean Expert', authority: 'expert',
      status: 'completed', activity: 'Result ready', report_path: '/tmp/report.md',
      updated_at: '2026-09-17T11:10:00Z',
    },
    title: 'report.md',
  }]);

  expect(entries.map((entry) => entry.kind === 'coordinator' ? entry.item.item_id : entry.agent.agent_id))
    .toEqual(['coordinator-early', 'expert-1', 'coordinator-late']);
});

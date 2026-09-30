import {describe, expect, it} from 'vitest';

import {readWorkflowMode, workflowModeStorageKey, writeWorkflowMode} from './workflow-mode.js';

describe('workflow mode', () => {
  it('defaults to standard mode and remembers research per task', () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
    };
    const first = workflowModeStorageKey('/project', 'task_one');
    const second = workflowModeStorageKey('/project', 'task_two');

    expect(readWorkflowMode(storage, first)).toBe('standard');
    writeWorkflowMode(storage, first, 'research');
    expect(readWorkflowMode(storage, first)).toBe('research');
    expect(readWorkflowMode(storage, second)).toBe('standard');
  });
});

export type WorkflowMode = 'standard' | 'research';

const PREFIX = 'oceanx.workflow-mode.v1';

export function workflowModeStorageKey(workspacePath: string | null, taskId: string | null): string | null {
  if (!workspacePath || !taskId) return null;
  return `${PREFIX}:${encodeURIComponent(workspacePath)}:${encodeURIComponent(taskId)}`;
}

export function readWorkflowMode(storage: Pick<Storage, 'getItem'>, key: string | null): WorkflowMode {
  return key && storage.getItem(key) === 'research' ? 'research' : 'standard';
}

export function writeWorkflowMode(
  storage: Pick<Storage, 'setItem'>,
  key: string | null,
  mode: WorkflowMode,
): void {
  if (key) storage.setItem(key, mode);
}

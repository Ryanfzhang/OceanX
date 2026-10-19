export function revisionFromRequestFailure(error: unknown): number | null {
  if (error === null || typeof error !== 'object' || Array.isArray(error)) return null;
  const record = error as Record<string, unknown>;
  if (record.code !== 'workspace_revision_conflict') return null;
  const details = record.details;
  if (details === null || typeof details !== 'object' || Array.isArray(details)) return null;
  const revision = (details as Record<string, unknown>).current_workspace_revision;
  return typeof revision === 'number' && Number.isSafeInteger(revision) && revision >= 0
    ? revision
    : null;
}

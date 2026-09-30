import type {EventPayload} from './types.js';

export const NODE_LABELS = ['decision-changing', 'informative-but-not-decisive', 'misleading-or-wasteful'] as const;
export type NodeLabel = typeof NODE_LABELS[number];
export type LabelCandidate = {
  node_id: string;
  question: string;
  status: string;
  result: string;
  suggested: NodeLabel | null;
  suggested_source: 'auto' | 'judge' | 'human' | null;
  human: NodeLabel | null;
};
export type PolicyOption = {name: string; version: string; description: string};
export type PolicyOverview = {active: string; available: PolicyOption[]};

const str = (value: unknown): string => (typeof value === 'string' ? value : '');
const records = (value: unknown): Record<string, unknown>[] => (Array.isArray(value) ? value : [])
  .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object');
const label = (value: unknown): NodeLabel | null => (NODE_LABELS as readonly unknown[]).includes(value) ? value as NodeLabel : null;

export function parseLabelCandidates(result: EventPayload): LabelCandidate[] {
  return records(result.labels).filter((item) => /^B\d+(\.\d+)*$/.test(str(item.node_id))).map((item) => ({
    node_id: str(item.node_id),
    question: str(item.question),
    status: str(item.status),
    result: str(item.result),
    suggested: label(item.suggested),
    suggested_source: item.suggested_source === 'auto' || item.suggested_source === 'judge' || item.suggested_source === 'human' ? item.suggested_source : null,
    human: label(item.human),
  }));
}

export function parsePolicyOverview(result: EventPayload): PolicyOverview | null {
  const raw = result.policies;
  if (!raw || typeof raw !== 'object') return null;
  const data = raw as Record<string, unknown>;
  return {
    active: str(data.active),
    available: records(data.available).map((item) => ({name: str(item.name), version: str(item.version), description: str(item.description)})).filter((item) => item.name),
  };
}

import type {EventPayload} from './types.js';

export type LessonRole = 'coordinator' | 'expert';
export type EvidenceTask = {task_key: string; question: string};
export type LessonProposal = {
  id: string;
  kind: 'add' | 'retire';
  role: LessonRole;
  lesson_id: string | null;
  /** The skill and section the lesson is written into once approved (empty for a retirement). */
  skill: string;
  section: string;
  text: string;
  applies_when: string;
  rationale: string;
  created_at: string;
  evidence_tasks: {supporting: EvidenceTask[]; counter: EvidenceTask[]};
};
export type ActiveLesson = {
  id: string;
  role: LessonRole;
  skill: string;
  section: string;
  text: string;
  applies_when: string;
  approved_by?: string;
  approved_at?: string;
  edited?: boolean;
  evidence_tasks: {supporting: EvidenceTask[]; counter: EvidenceTask[]};
};
export type LessonLimits = {max_active_per_role: number; max_words: number; max_condition_words: number; min_support: number};
export type LessonOverview = {
  pending: LessonProposal[];
  active: ActiveLesson[];
  limits: LessonLimits;
  lessonsVersion: string | null;
  digests: number;
  lastConsolidatedAt: string | null;
};

const DEFAULT_LIMITS: LessonLimits = {max_active_per_role: 12, max_words: 40, max_condition_words: 25, min_support: 3};

const text = (value: unknown): string => (typeof value === 'string' ? value : '');
const role = (value: unknown): LessonRole => (value === 'expert' ? 'expert' : 'coordinator');

function evidence(value: unknown): {supporting: EvidenceTask[]; counter: EvidenceTask[]} {
  const record = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>;
  const list = (side: unknown): EvidenceTask[] => (Array.isArray(side) ? side : [])
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map((item) => ({task_key: text(item.task_key), question: text(item.question)}))
    .filter((item) => item.task_key);
  return {supporting: list(record.supporting), counter: list(record.counter)};
}

/** Defensive parse of the backend's `lessons` overview; unknown fields are ignored. */
export function parseLessonOverview(result: EventPayload): LessonOverview | null {
  const raw = result.lessons;
  if (!raw || typeof raw !== 'object') return null;
  const data = raw as Record<string, unknown>;
  const records = (value: unknown) => (Array.isArray(value) ? value : [])
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object');
  const limits = (data.limits && typeof data.limits === 'object' ? data.limits : {}) as Record<string, unknown>;
  const numberOr = (value: unknown, fallback: number) => (typeof value === 'number' && Number.isFinite(value) ? value : fallback);
  return {
    pending: records(data.pending).filter((item) => /^lp_[a-f0-9]{12}$/.test(text(item.id))).map((item) => ({
      id: text(item.id),
      kind: item.kind === 'retire' ? 'retire' : 'add',
      role: role(item.role),
      lesson_id: typeof item.lesson_id === 'string' ? item.lesson_id : null,
      skill: text(item.skill),
      section: text(item.section),
      text: text(item.text),
      applies_when: text(item.applies_when),
      rationale: text(item.rationale),
      created_at: text(item.created_at),
      evidence_tasks: evidence(item.evidence_tasks),
    })),
    active: records(data.active).filter((item) => text(item.id)).map((item) => ({
      id: text(item.id),
      role: role(item.role),
      skill: text(item.skill),
      section: text(item.section),
      text: text(item.text),
      applies_when: text(item.applies_when),
      approved_by: text(item.approved_by) || undefined,
      approved_at: text(item.approved_at) || undefined,
      edited: item.edited === true,
      evidence_tasks: evidence(item.evidence_tasks),
    })),
    limits: {
      max_active_per_role: numberOr(limits.max_active_per_role, DEFAULT_LIMITS.max_active_per_role),
      max_words: numberOr(limits.max_words, DEFAULT_LIMITS.max_words),
      max_condition_words: numberOr(limits.max_condition_words, DEFAULT_LIMITS.max_condition_words),
      min_support: numberOr(limits.min_support, DEFAULT_LIMITS.min_support),
    },
    lessonsVersion: typeof data.lessons_version === 'string' ? data.lessons_version : null,
    digests: numberOr(data.digests, 0),
    lastConsolidatedAt: typeof data.last_consolidated_at === 'string' ? data.last_consolidated_at : null,
  };
}

export function wordCount(value: string): number {
  return value.trim() ? value.trim().split(/\s+/).length : 0;
}

/** Mirrors the backend limits so the Approve button is disabled for drafts it would reject. */
export function approvalProblem(draft: {text: string; appliesWhen: string}, proposal: LessonProposal, overview: LessonOverview): string | null {
  if (proposal.kind === 'retire') return null;
  const words = wordCount(draft.text);
  const conditionWords = wordCount(draft.appliesWhen);
  if (!words) return 'empty-text';
  if (words > overview.limits.max_words) return 'text-too-long';
  if (!conditionWords) return 'empty-condition';
  if (conditionWords > overview.limits.max_condition_words) return 'condition-too-long';
  const activeForRole = overview.active.filter((lesson) => lesson.role === proposal.role).length;
  if (activeForRole >= overview.limits.max_active_per_role) return 'role-full';
  return null;
}

/** Only send edited fields, so an unedited approval keeps the proposal's exact wording. */
export function decisionPayload(proposal: LessonProposal, decision: 'approve' | 'reject', draft: {text: string; appliesWhen: string}, reason: string): EventPayload {
  const payload: EventPayload = {proposal_id: proposal.id, decision};
  if (decision === 'approve' && proposal.kind === 'add') {
    if (draft.text.trim() !== proposal.text) payload.text = draft.text.trim();
    if (draft.appliesWhen.trim() !== proposal.applies_when) payload.applies_when = draft.appliesWhen.trim();
  }
  if (reason.trim()) payload.reason = reason.trim();
  return payload;
}

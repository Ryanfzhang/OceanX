import type {EventPayload} from './types.js';

/** The owner's view of one lesson or tool. */
export type Mark = 'right' | 'wrong';
export type LibraryKind = 'lesson' | 'tool';
export type EvidenceTask = {task_key: string; question: string};
export type Lesson = {
  id: string;
  skill: string;
  text: string;
  applies_when: string;
  active: boolean;
  human: Mark | null;
  /** Finished tasks whose skills carried this lesson, and those that named it. */
  tasksShown: number;
  tasksCited: number;
  retiredReason: string;
  evidence_tasks: {supporting: EvidenceTask[]; counter: EvidenceTask[]};
};
/** One skill that takes lessons: how many it holds, what they are about and who reads them. */
export type LessonSkill = {name: string; about: string; limit: number; reader: 'coordinator' | 'expert'; lessons: Lesson[]};
export type Tool = {
  name: string;
  signature: string;
  summary: string;
  learned: boolean;
  /** Whether the skill lists it now. An unlisted built-in function can still be imported. */
  shown: boolean;
  human: Mark | null;
  reason: string;
  tasks: number;
  tasksCalled: number;
  calls: number;
  /** Only for a learned tool. */
  code: string;
  test: string;
};
export type LibraryChange = {at: string; kind: LibraryKind; item: string; change: string; by: string; reason: string};
export type Library = {
  skills: LessonSkill[];
  retired: Lesson[];
  tools: Tool[];
  /** Newest first, lessons and tools together. */
  changes: LibraryChange[];
  minSupport: number;
  version: string | null;
  digests: number;
  lastReviewedAt: string | null;
};

const str = (value: unknown): string => (typeof value === 'string' ? value : '');
const count = (value: unknown): number => (typeof value === 'number' && Number.isFinite(value) ? value : 0);
const record = (value: unknown): Record<string, unknown> => (value && typeof value === 'object' ? value as Record<string, unknown> : {});
const records = (value: unknown): Record<string, unknown>[] => (Array.isArray(value) ? value : [])
  .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object');
const mark = (value: unknown): Mark | null => (value === 'right' || value === 'wrong' ? value : null);
// The backend refuses any other id, so a row that could not be marked is not shown.
const ID = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;

function evidence(value: unknown): {supporting: EvidenceTask[]; counter: EvidenceTask[]} {
  const list = (side: unknown): EvidenceTask[] => records(side)
    .map((item) => ({task_key: str(item.task_key), question: str(item.question)}))
    .filter((item) => item.task_key);
  return {supporting: list(record(value).supporting), counter: list(record(value).counter)};
}

function lesson(item: Record<string, unknown>): Lesson {
  return {
    id: str(item.id),
    skill: str(item.skill),
    text: str(item.text),
    applies_when: str(item.applies_when),
    active: item.status === 'active',
    human: mark(item.human),
    tasksShown: count(item.tasks_shown),
    tasksCited: count(item.tasks_cited),
    retiredReason: str(item.retired_reason),
    evidence_tasks: evidence(item.evidence_tasks),
  };
}

function changes(value: unknown, kind: LibraryKind): LibraryChange[] {
  return records(value).map((item) => ({
    at: str(item.at), kind, item: str(item[kind]), change: str(item.change), by: str(item.by), reason: str(item.reason),
  })).filter((item) => item.item && item.change);
}

/** Defensive parse of the backend's `library` overview; unknown fields are ignored. */
export function parseLibrary(result: EventPayload): Library | null {
  const raw = result.library;
  if (!raw || typeof raw !== 'object') return null;
  const data = raw as Record<string, unknown>;
  const lessons = (value: unknown) => records(value).filter((item) => ID.test(str(item.id))).map(lesson);
  return {
    skills: records(data.skills).filter((item) => str(item.name)).map((item) => ({
      name: str(item.name),
      about: str(item.about),
      limit: count(item.limit),
      reader: item.reader === 'coordinator' ? 'coordinator' : 'expert',
      lessons: lessons(item.lessons),
    })),
    retired: lessons(data.retired).reverse(),
    tools: records(data.tools).filter((item) => ID.test(str(item.name))).map((item) => ({
      name: str(item.name),
      signature: str(item.signature) || str(item.name),
      summary: str(item.summary),
      learned: item.source === 'learned',
      shown: item.shown === true,
      human: mark(item.human),
      reason: str(item.reason),
      tasks: count(record(item.stats).tasks),
      tasksCalled: count(record(item.stats).tasks_called),
      calls: count(record(item.stats).calls),
      code: str(item.code),
      test: str(item.test),
    })),
    changes: [...changes(data.changes, 'lesson'), ...changes(data.tool_changes, 'tool')]
      .sort((a, b) => b.at.localeCompare(a.at)),
    minSupport: count(record(data.limits).min_support) || 3,
    version: str(data.version) || null,
    digests: count(data.digests),
    lastReviewedAt: str(data.last_reviewed_at) || null,
  };
}

export type UpdateSummary = {
  digested: number;
  /** False when no task finished since the last review, so the meta-agent was not asked. */
  reviewed: boolean;
  /** Different research questions among the finished tasks; lessons and tools need three. */
  questions: number | null;
  lessonChanges: number;
  toolsAdded: string[];
  toolsRemoved: string[];
  refused: number;
};

/** What "Update now" did, from the `update` part of the reply. */
export function summarizeUpdate(result: EventPayload): UpdateSummary | null {
  if (!result.update || typeof result.update !== 'object') return null;
  const update = result.update as Record<string, unknown>;
  const lessons = record(update.lessons);
  const tools = record(update.tools);
  const names = (value: unknown): string[] => (Array.isArray(value) ? value : []).filter((item): item is string => typeof item === 'string');
  return {
    digested: count(record(update.consolidation).digested),
    reviewed: count(lessons.skills_reviewed) > 0 || 'tools' in update,
    questions: typeof lessons.questions === 'number' ? lessons.questions : null,
    lessonChanges: records(lessons.changes).length,
    toolsAdded: names(tools.created),
    toolsRemoved: names(record(update.tool_usage).removed),
    refused: records(lessons.rejected).length + records(tools.rejected).length,
  };
}

export function markPayload(kind: LibraryKind, id: string, verdict: Mark): EventPayload {
  return {kind, id, verdict};
}
